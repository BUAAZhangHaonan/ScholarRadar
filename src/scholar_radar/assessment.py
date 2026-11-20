import json
import re

from .db import database, key, rows
from .evidence import claim
from .factors import activity, put_values
from .models import ask
from .source_labels import label_inputs
from .profile import get_profile
from .settings import ROOT, dump, now


def packet(db, run):
    rid = run["id"]
    recent = rows(
        db,
        """SELECT w.id wid,w.title,w.metadata,w.first_seen,e.id eid,e.quote,c.statement FROM readings l
        JOIN works w ON w.id=json_extract(l.outcome,'$.work_id')
        JOIN documents d ON d.work_id=w.id JOIN revisions v ON v.document_id=d.id
        JOIN evidence e ON e.revision_id=v.id JOIN claim_evidence ce ON ce.evidence_id=e.id
        JOIN claims c ON c.id=ce.claim_id AND c.kind='system_inference'
        WHERE l.run_id=? AND l.status='done' ORDER BY w.id,e.start""",
        (rid,),
    )
    history = rows(
        db,
        """SELECT w.id wid,w.title,w.metadata,w.first_seen,e.id eid,e.quote,NULL statement FROM
        snapshots s JOIN assessment_reviews ar ON ar.snapshot_id=s.id AND ar.verdict='supported' JOIN snapshot_evidence se ON se.snapshot_id=s.id JOIN evidence e ON e.id=se.evidence_id
        JOIN revisions v ON v.id=e.revision_id JOIN documents d ON d.id=v.document_id JOIN works w ON w.id=d.work_id
        WHERE s.as_of<=? ORDER BY s.generated_at DESC LIMIT 90""",
        (run["as_of"] + "T23:59:59",),
    )
    papers = {}
    for r in recent + history:
        meta = json.loads(r["metadata"])
        p = papers.setdefault(
            r["wid"],
            {
                "work_id": r["wid"],
                "title": r["title"],
                "date": meta.get("published_date") or None,
                "year": meta.get("year"),
                "first_seen": r["first_seen"],
                "analysis": (r["statement"] or "")[:780],
                "quotes": {},
            },
        )
        if len(p["quotes"]) < 4:
            p["quotes"][r["eid"]] = r["quote"][:1400]
    for wid, p in papers.items():
        p["resources"] = rows(
            db,
            """SELECT DISTINCT res.url,o.status,o.observed_at,e.quote FROM work_resources m
            JOIN resources res ON res.id=m.resource_id JOIN resource_observations o ON o.resource_id=res.id
            LEFT JOIN evidence e ON e.id=o.evidence_id WHERE m.work_id=? AND o.status='accessible'
            ORDER BY o.observed_at DESC LIMIT 3""",
            (wid,),
        )
    jobs = rows(
        db,
        """SELECT e.id,e.quote,p.title,p.url,o.status FROM posting_observations o JOIN postings p ON p.id=o.posting_id
        JOIN evidence e ON e.revision_id=o.revision_id WHERE o.status='advertised'
        AND o.verified_at=(SELECT max(o2.verified_at) FROM posting_observations o2 WHERE o2.posting_id=p.id)
        ORDER BY e.start LIMIT 14""",
    )
    previous = {}
    for r in db.execute(
        "SELECT s.dir_id,s.id,s.body FROM snapshots s JOIN assessment_reviews a ON a.snapshot_id=s.id WHERE a.verdict='supported' ORDER BY s.generated_at DESC"
    ):
        if r["dir_id"] not in previous:
            previous[r["dir_id"]] = {
                "snapshot_id": r["id"],
                "judgment": json.loads(r["body"])["judgment"],
            }
    return papers, jobs, previous


def validate_card(card, papers, jobs):
    neighbor = card.get("nearest")
    if isinstance(neighbor, dict):
        if neighbor.get("work_id") not in papers:
            raise ValueError("最近邻作品不在输入集合")
        card["nearest"] = "　".join(
            str(neighbor[k])
            for k in ("title", "similarity", "difference")
            if neighbor.get(k)
        )
    for field in (
        "title",
        "judgment",
        "change",
        "nearest",
        "question",
        "method",
        "setting",
    ):
        if not isinstance(card.get(field), str) or not card[field].strip():
            raise ValueError("方向卡缺少 " + field)
    works = list(dict.fromkeys(card.get("work_ids", [])))
    ids = list(dict.fromkeys(card.get("evidence_ids", [])))
    if not works or not set(works) <= papers.keys():
        raise ValueError("方向引用了输入之外的作品")
    allowed = {eid for w in works for eid in papers[w]["quotes"]}
    if not ids or not set(ids) <= allowed:
        raise ValueError("方向引用了输入之外的论文证据")
    timeline = []
    for h in card.get("history", []):
        wid = h.get("work_id")
        refs = h.get("evidence_ids") or []
        if (
            wid not in works
            or not refs
            or not set(refs) <= papers[wid]["quotes"].keys()
        ):
            continue
        p = papers[wid]
        published = p["date"] or (str(p["year"]) if p["year"] else None)
        timeline.append(
            {
                "work_id": wid,
                "date": published,
                "first_observed": p["first_seen"],
                "event": str(h.get("event") or "")[:500],
                "evidence_ids": refs,
            }
        )
    if not timeline:
        raise ValueError("研究历史没有可回查的工作与引文")
    card["history"] = sorted(timeline, key=lambda x: x["date"] or x["first_observed"])
    h = card.get("forecast") or {}
    if (
        not all(
            h.get(k)
            for k in ("hypothesis", "confirm", "refute", "horizon", "evidence_ids")
        )
        or not set(h["evidence_ids"]) <= allowed
    ):
        raise ValueError("预测缺少来源、期限或可区分的观测")
    job = card.get("job_match")
    if job and (
        not job.get("evidence_ids")
        or not set(job["evidence_ids"]) <= {x["id"] for x in jobs}
    ):
        card["job_match"] = None
    if not isinstance(card.get("action"), dict) or card["action"].get("kind") not in (
        "read",
        "verify",
        "observe",
    ):
        raise ValueError("行动类型无效")
    if not isinstance(card.get("feasibility"), dict):
        raise ValueError("缺少个人条件")
    narrative = " ".join([card["judgment"], card["change"], card["nearest"]])
    for metric in re.findall(r"\d+(?:\.\d+)?\s*[%％]", narrative):
        number = re.search(r"\d+(?:\.\d+)?", metric)[0]
        if not any(number in q for w in works for q in papers[w]["quotes"].values()):
            raise ValueError("数字缺少原文依据")
    cited = set(ids) | set(h["evidence_ids"])
    for row in timeline:
        cited.update(row["evidence_ids"])
    return sorted(cited), works


async def assess(run):
    with database() as db:
        papers, jobs, previous = packet(db, run)
        dirs = rows(
            db,
            "SELECT id,title,question,method,setting,layer FROM directions WHERE status!='merged'",
        )
        profile = get_profile(db, run["profile_id"])
        past = {
            r[0]
            for r in db.execute(
                "SELECT evidence_id FROM assessed_inputs WHERE profile_id=? AND rule_version='evidence-v2'",
                (profile["id"],),
            )
        }
    all_ids = {eid for p in papers.values() for eid in p["quotes"]} | {
        j["id"] for j in jobs
    }
    if not papers or (previous and not all_ids - past):
        return {"snapshots": [], "reason": "没有新的有效证据"}
    instruction = (ROOT / "prompts/direction-assessment.txt").read_text()
    paper_input, job_input, restore_ids = label_inputs(papers, jobs)
    data = await ask(
        "synthesis",
        profile["strong_model"],
        instruction,
        {
            "papers": paper_input,
            "jobs": job_input,
            "directions": dirs,
            "previous": previous,
            "as_of": run["as_of"],
            "assets": profile["assets"],
            "compute": profile["compute"],
            "goals": profile["goals"],
            "weeks": profile["validation_weeks"],
        },
        run["id"],
        max_tokens=8500,
    )
    saved = []
    rejected = []
    for raw_card in data.get("cards", [])[: profile["daily_limit"]]:
        card = restore_ids(raw_card)
        try:
            ids, works = validate_card(card, papers, jobs)
            with database(write=True) as db:
                did = card.get("direction_id")
                if did == "new":
                    did = key(
                        "candidate", card["question"], card["method"], card["setting"]
                    )
                    db.execute(
                        "INSERT OR IGNORE INTO directions VALUES(?,?,?,'candidate',?,?,?,'1',?)",
                        (
                            did,
                            card["title"],
                            card.get("layer", "adjacent"),
                            card["question"],
                            card["method"],
                            card["setting"],
                            now(),
                        ),
                    )
                if not db.execute(
                    "SELECT id FROM directions WHERE id=?", (did,)
                ).fetchone():
                    raise ValueError("未知方向")
                for wid in works:
                    db.execute(
                        "INSERT OR IGNORE INTO memberships VALUES(?,?,? ,?,?)",
                        (did, wid, "1", dump(ids), now()),
                    )
                jobids = (card.get("job_match") or {}).get("evidence_ids", [])
                refs = sorted(set(ids) | set(jobids))
                old = db.execute(
                    "SELECT id FROM snapshots WHERE dir_id=? ORDER BY generated_at DESC LIMIT 1",
                    (did,),
                ).fetchone()
                older = (
                    {
                        r[0]
                        for r in db.execute(
                            "SELECT evidence_id FROM snapshot_evidence WHERE snapshot_id=?",
                            (old[0],),
                        )
                    }
                    if old
                    else set()
                )
                card.update(
                    previous_snapshot=old[0] if old else None,
                    new_evidence_ids=sorted(set(refs) - older),
                )
                if old and not card["new_evidence_ids"]:
                    continue
                when = now()
                sig = key(refs)
                sid = key(did, run["as_of"], profile["id"], run["scope"], "1", sig)
                db.execute(
                    "INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        sid,
                        did,
                        run["id"],
                        when,
                        when,
                        profile["id"],
                        run["scope"],
                        "1",
                        dump(card),
                        sig,
                    ),
                )
                for eid in refs:
                    db.execute(
                        "INSERT OR IGNORE INTO snapshot_evidence VALUES(?,?)",
                        (sid, eid),
                    )
                for kind, statement, eids in [
                    ("system_inference", card["judgment"], ids),
                    (
                        "research_hypothesis",
                        card["forecast"]["hypothesis"],
                        card["forecast"]["evidence_ids"],
                    ),
                ]:
                    cid = claim(
                        db,
                        kind,
                        statement,
                        eids,
                        refs,
                        {"scope": run["scope"], "nearest": card["nearest"]},
                    )
                    db.execute(
                        "INSERT OR IGNORE INTO snapshot_claims VALUES(?,?)", (sid, cid)
                    )
                put_values(
                    db, sid, card, refs, activity(db, did, run["scope"], run["as_of"])
                )
                action = card["action"]
                db.execute(
                    "INSERT OR IGNORE INTO actions VALUES(?,?,?,?,?,?,?)",
                    (
                        key(sid, action["title"]),
                        sid,
                        action["title"],
                        action["kind"],
                        "proposed",
                        dump(action),
                        when,
                    ),
                )
                saved.append(sid)
        except (ValueError, KeyError, TypeError) as exc:
            rejected.append(str(exc))
    if rejected and not saved:
        raise ValueError("方向卡校验失败：" + " / ".join(rejected))
    with database(write=True) as db:
        for eid in all_ids:
            db.execute(
                "INSERT OR IGNORE INTO assessed_inputs VALUES(?,'evidence-v2',?,?)",
                (profile["id"], eid, run["id"]),
            )
    return {"snapshots": saved, "rejected": rejected}
