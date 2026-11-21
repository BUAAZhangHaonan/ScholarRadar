import json
import re

from .db import database, key, rows
from .evidence import claim
from . import changes
from .research_materials import select_papers, signature, cutoff_for, terms
from .factors import activity, put_values
from .models import ask
from .source_labels import label_inputs
from .profile import get_profile
from .settings import ROOT, dump, now


def packet(db, run, direction=None, events=(), extra_works=()):
    papers = select_papers(db, run, direction, events, extra_works)
    jobs = rows(
        db,
        """SELECT e.id,e.quote,p.title,p.url,p.organization_id,o.status FROM posting_observations o JOIN postings p ON p.id=o.posting_id
        JOIN evidence e ON e.revision_id=o.revision_id WHERE o.status='advertised' AND o.verified_at<=?
        AND o.verified_at=(SELECT max(o2.verified_at) FROM posting_observations o2 WHERE o2.posting_id=p.id AND o2.verified_at<=?)
        ORDER BY e.start LIMIT 14""",
        (cutoff_for(run), cutoff_for(run)),
    )
    prefs = get_profile(db, run["profile_id"])
    excluded = {
        v.strip().casefold()
        for v in prefs["deferred_companies"] + prefs["excluded_companies"]
    }
    targets = {v.strip().casefold() for v in prefs["target_companies"]}
    eligible = []
    for j in jobs:
        aliases = [
            r[0].casefold()
            for r in db.execute(
                """SELECT a.alias FROM aliases a WHERE a.organization_id=? OR a.organization_id=
            (SELECT parent_id FROM organizations WHERE id=?) UNION SELECT name FROM organizations WHERE id=?""",
                (j["organization_id"], j["organization_id"], j["organization_id"]),
            )
        ]
        if (
            not aliases
            or excluded.intersection(aliases)
            or (targets and not targets.intersection(aliases))
        ):
            continue
        eligible.append(j)
    jobs = eligible
    previous = {}
    for r in db.execute(
        "SELECT s.dir_id,s.id,s.body,s.as_of FROM snapshots s JOIN assessment_reviews a ON a.snapshot_id=s.id WHERE a.verdict='supported' ORDER BY s.generated_at DESC"
    ):
        if r["as_of"] <= cutoff_for(run) and r["dir_id"] not in previous:
            previous[r["dir_id"]] = {
                "snapshot_id": r["id"],
                "judgment": json.loads(r["body"])["judgment"],
                "as_of": r["as_of"],
                "role": "当时已发表的判断",
            }
    return papers, jobs, previous


def validate_card(card, papers, jobs):
    neighbor = card.get("nearest")
    if isinstance(neighbor, dict):
        if neighbor.get("work_id") not in papers or not all(
            isinstance(neighbor.get(k), str) and neighbor[k].strip()
            for k in ("title", "similarity", "difference")
        ):
            raise ValueError("最近邻需包含可核对的作品、共同点和具体差别")
    elif not isinstance(neighbor, str) or not neighbor.strip():
        raise ValueError("缺少最近邻材料")
    for field in ("title", "judgment", "change", "question", "method", "setting"):
        if not isinstance(card.get(field), str) or not card[field].strip():
            raise ValueError("方向卡缺少 " + field)
    works = list(dict.fromkeys(card.get("work_ids", [])))
    ids = list(dict.fromkeys(card.get("evidence_ids", [])))
    if not works or not set(works) <= papers.keys():
        raise ValueError("方向引用了输入之外的作品")
    allowed = {eid for w in works for eid in papers[w]["quotes"]}
    linked = [r for wid in works for r in papers[wid].get("reading_records", [])]
    record_ids = card.get("reading_record_ids") or []
    if record_ids and (
        not isinstance(record_ids, list)
        or not set(record_ids) <= {r["id"] for r in linked}
    ):
        raise ValueError("方向引用了本次材料以外的论文分析")
    asset_ids = card.get("resource_evidence_ids") or []
    if not isinstance(asset_ids, list) or not set(asset_ids) <= {
        a["evidence_id"] for wid in works for a in papers[wid].get("artifacts", [])
    }:
        raise ValueError("资源状态缺少实际文件或发布条目的核验依据")
    if not ids or not set(ids) <= allowed:
        raise ValueError("方向引用了输入之外的论文证据")
    timeline = []
    for h in card.get("history", []):
        wid = h.get("work_id")
        refs = h.get("evidence_ids") or []
        if wid not in works or not refs:
            raise ValueError("历史事项缺少有效作品及引文")
        p = papers[wid]
        role = h.get("version_role", "current")
        ref_revision = p.get("revision_id")
        ref_version = p.get("version")
        if role == "historical_comparison":
            old = [
                r
                for r in p.get("historical_comparison", [])
                if r["revision_id"] == h.get("revision_id")
            ]
            if not old or not set(refs) <= {
                eid for rec in old for eid in rec["quotes"]
            }:
                raise ValueError("历史比较没有指向输入中的明确旧修订")
            ref_revision, ref_version = old[0]["revision_id"], old[0]["version"]
        elif role != "current" or not set(refs) <= p["quotes"].keys():
            raise ValueError("当前结果混入其他修订的引文")
        published = p["date"] or (str(p["year"]) if p["year"] else None)
        timeline.append(
            {
                "work_id": wid,
                "date": published,
                "first_observed": p["first_seen"],
                "version_role": role,
                "revision_id": ref_revision,
                "version": ref_version,
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
    narrative = " ".join([card["judgment"], card["change"], dump(card["nearest"])])
    for metric in re.findall(r"\d+(?:\.\d+)?\s*[%％]", narrative):
        number = re.search(r"\d+(?:\.\d+)?", metric)[0]
        if not any(number in q for w in works for q in papers[w]["quotes"].values()):
            raise ValueError("数字缺少原文依据")
    cited = set(ids) | set(h["evidence_ids"])
    for row in timeline:
        cited.update(row["evidence_ids"])
    return sorted(cited), works


def persist_card(db, run, profile, card, ids, works, papers, sig):
    did = card.get("direction_id")
    if did == "new":
        did = key("candidate", card["question"], card["method"], card["setting"])
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
    if not db.execute("SELECT id FROM directions WHERE id=?", (did,)).fetchone():
        raise ValueError("未知方向")
    for wid in works:
        db.execute(
            "INSERT OR IGNORE INTO memberships VALUES(?,?,? ,?,?)",
            (did, wid, "1", dump(ids), now()),
        )
    jobids = (card.get("job_match") or {}).get("evidence_ids", [])
    refs = sorted(set(ids) | set(jobids) | set(card.get("resource_evidence_ids") or []))
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
    when = now()
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
    for wid in works:
        for record in papers[wid]["reading_records"]:
            explicit = card.get("reading_record_ids") or []
            if record["id"] in explicit or (
                not explicit and set(record["evidence_ids"]) & set(ids)
            ):
                db.execute(
                    "INSERT OR IGNORE INTO snapshot_reading_records VALUES(?,?)",
                    (sid, record["id"]),
                )
    for wid in works:
        for old_note in papers[wid].get("historical_comparison", []):
            if set(old_note["quotes"]) & set(ids):
                db.execute(
                    "INSERT OR IGNORE INTO snapshot_reading_records VALUES(?,?)",
                    (sid, old_note["record_id"]),
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
        db.execute("INSERT OR IGNORE INTO snapshot_claims VALUES(?,?)", (sid, cid))
    put_values(db, sid, card, refs, activity(db, did, run["scope"], run["as_of"]))
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
    return sid, did


def unassigned_targets(db, events, directions, run):
    targeted = {}
    for e in events:
        if e["direction_id"]:
            targeted.setdefault(e["direction_id"], []).append(e)
            continue
        if e["kind"] != "reading":
            continue
        wid = e["entity_id"]
        linked = changes.work_directions(db, wid)
        if not linked:
            note = db.execute(
                """SELECT w.title,r.topic,c.statement FROM reading_records r JOIN works w ON w.id=r.work_id
                             JOIN claims c ON c.id=r.id WHERE r.work_id=? AND r.recorded_at<=? ORDER BY r.recorded_at DESC LIMIT 1""",
                (wid, cutoff_for(run)),
            ).fetchone()
            if note:
                words, han = terms(" ".join(note))
                matches = []
                for d in directions:
                    dw, dh = terms(
                        " ".join(
                            d[k] for k in ("title", "question", "method", "setting")
                        )
                    )
                    similarities = len(dw & words) + len(dh & han)
                    if similarities:
                        matches.append((similarities, d["id"]))
                if matches:
                    best = max(x[0] for x in matches)
                    linked = {did for score, did in matches if score == best}
        for did in linked or {None}:
            targeted.setdefault(did, []).append(e)
    return targeted


async def assess(run, direction_ids=None):
    with database() as db:
        profile = get_profile(db, run["profile_id"])
        directions = rows(
            db,
            "SELECT id,title,question,method,setting,layer,definition_version FROM directions WHERE status!='merged'",
        )
        events = changes.pending(db, direction_ids)
        grouped = unassigned_targets(db, events, directions, run)
        if direction_ids is not None:
            for did in direction_ids:
                grouped.setdefault(did, [])
    if not grouped:
        return {"snapshots": [], "reason": "没有与研究方向有关的新输入"}
    catalog = {d["id"]: d for d in directions}
    instruction = (ROOT / "prompts/direction-assessment.txt").read_text()
    saved = []
    rejected = []
    handled = []
    failed_event_ids = set()
    for target, trigger in grouped.items():
        direction = catalog.get(target)
        with database() as db:
            papers, jobs, previous = packet(db, run, direction, trigger)
            versions = changes.input_versions(db, target) if target else []
            results = changes.research_outcomes(db, target) if target else []
            sig = signature(
                direction, profile["id"], run["scope"], papers, jobs, versions, results
            )
            done = (
                db.execute(
                    "SELECT 1 FROM direction_assessment_inputs WHERE direction_id=? AND profile_id=? AND signature=?",
                    (target, profile["id"], sig),
                ).fetchone()
                if target
                else None
            )
        if not papers or done or (not target and len(papers) < 2):
            handled.extend(e["id"] for e in trigger)
            continue
        paper_input, job_input, restore_ids = label_inputs(papers, jobs)
        old = previous.get(target) if target else None
        inputs = {
            "papers": paper_input,
            "jobs": job_input,
            "direction": direction,
            "previous": old,
            "change_types": sorted({e["kind"] for e in trigger}),
            "recorded_user_outcomes": results,
            "as_of": run["as_of"],
            "assets": profile["assets"],
            "compute": profile["compute"],
            "goals": profile["goals"],
            "weeks": profile["validation_weeks"],
        }
        data = await ask(
            "synthesis",
            profile["strong_model"],
            instruction,
            inputs,
            run["id"],
            max_tokens=6500,
        )
        candidates = data.get("cards")
        if not isinstance(candidates, list):
            raise ValueError("方向评估未返回有效列表")
        errors = []
        with database(write=True) as db:
            for raw in candidates[:1]:
                card = restore_ids(raw)
                db.execute("SAVEPOINT proposed_card")
                try:
                    if card.get("direction_id") != (target or "new"):
                        raise ValueError("方向卡超出本次评估对象")
                    nearest = card.get("nearest")
                    if (
                        isinstance(nearest, list)
                        and nearest
                        and all(
                            isinstance(n, dict)
                            and n.get("work_id") in papers
                            and all(
                                isinstance(n.get(k), str) and n[k].strip()
                                for k in ("title", "similarity", "difference")
                            )
                            for n in nearest
                        )
                    ):
                        card["nearest_works"] = nearest
                        card["nearest"] = nearest[0]
                    if not isinstance(card.get("nearest"), dict):
                        raise ValueError("新增方向卡需要结构化的最近邻比较")
                    ids, works = validate_card(card, papers, jobs)
                    sid, did = persist_card(
                        db, run, profile, card, ids, works, papers, sig
                    )
                    db.execute("RELEASE proposed_card")
                    saved.append(sid)
                except (ValueError, KeyError, TypeError) as exc:
                    db.execute("ROLLBACK TO proposed_card")
                    db.execute("RELEASE proposed_card")
                    errors.append(str(exc))
            if not errors and target:
                db.execute(
                    "INSERT OR IGNORE INTO direction_assessment_inputs VALUES(?,?,?,?,?)",
                    (target, profile["id"], sig, run["id"], now()),
                )
        if errors:
            failed_event_ids.update(e["id"] for e in trigger)
            rejected.extend(errors)
        else:
            handled.extend(e["id"] for e in trigger)
    with database(write=True) as db:
        changes.consume(db, set(handled) - failed_event_ids)
    if rejected:
        raise ValueError("方向卡校验失败：" + " / ".join(rejected))
    return {"snapshots": saved, "processed_changes": list(dict.fromkeys(handled))}
