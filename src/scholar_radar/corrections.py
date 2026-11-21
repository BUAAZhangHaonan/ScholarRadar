import json
from .assessment import validate_card
from .gap_reading import fill_gaps
from .db import database, key, rows
from .evidence import claim
from .factors import activity, put_values
from .models import ask
from .profile import get_profile
from .settings import dump, now


def frozen_sources(db, snapshot):
    """Reword using only the exact published packet, even after another reading arrives."""
    card = json.loads(snapshot["body"])
    historical = {
        h.get("revision_id")
        for h in card.get("history", [])
        if h.get("version_role") == "historical_comparison"
    }
    papers = {}
    jobs = []
    for q in rows(
        db,
        """SELECT e.id,e.quote,e.revision_id,v.version,d.kind,d.work_id,w.first_seen,w.metadata
           FROM snapshot_evidence se JOIN evidence e ON e.id=se.evidence_id JOIN revisions v ON v.id=e.revision_id
           JOIN documents d ON d.id=v.document_id LEFT JOIN works w ON w.id=d.work_id WHERE se.snapshot_id=?""",
        (snapshot["id"],),
    ):
        if not q["work_id"]:
            if q["kind"] == "job":
                jobs.append(q)
            continue
        meta = json.loads(q["metadata"])
        w = papers.setdefault(
            q["work_id"],
            {
                "quotes": {},
                "date": meta.get("published_date"),
                "year": meta.get("year"),
                "first_seen": q["first_seen"],
                "reading_records": [],
                "artifacts": [],
                "historical_comparison": [],
            },
        )
        if q["revision_id"] in historical:
            old = next(
                (
                    v
                    for v in w["historical_comparison"]
                    if v["revision_id"] == q["revision_id"]
                ),
                None,
            )
            if old is None:
                old = {
                    "revision_id": q["revision_id"],
                    "version": q["version"],
                    "quotes": {},
                }
                w["historical_comparison"].append(old)
            old["quotes"][q["id"]] = q["quote"]
        else:
            if w.get("revision_id") not in (None, q["revision_id"]):
                raise ValueError("历史卡当前结果缺少唯一的修订依据")
            w.update(revision_id=q["revision_id"], version=q["version"])
            w["quotes"][q["id"]] = q["quote"]
    for wid, w in papers.items():
        w["reading_records"] = rows(
            db,
            """SELECT r.id FROM snapshot_reading_records x JOIN reading_records r ON r.id=x.record_id
            WHERE x.snapshot_id=? AND r.work_id=? AND r.revision_id=?""",
            (snapshot["id"], wid, w.get("revision_id")),
        )
        w["artifacts"] = rows(
            db,
            """SELECT DISTINCT a.evidence_id FROM snapshot_evidence se
              JOIN verified_artifacts a ON a.evidence_id=se.evidence_id JOIN work_resources wr ON wr.resource_id=a.resource_id
              WHERE se.snapshot_id=? AND wr.work_id=?""",
            (snapshot["id"], wid),
        )
    return papers, jobs


async def revise(run):
    supplementation = await fill_gaps(run)
    with database() as db:
        profile = get_profile(db, run["profile_id"])
        rejected = rows(
            db,
            """SELECT s.*,r.reason FROM snapshots s JOIN assessment_reviews r ON r.snapshot_id=s.id
            WHERE s.run_id=? AND r.verdict='needs_evidence' AND EXISTS(SELECT 1 FROM research_gaps g WHERE g.snapshot_id=s.id AND g.kind='wording') AND json_extract(s.body,'$.corrects') IS NULL
            AND NOT EXISTS(SELECT 1 FROM snapshots n WHERE json_extract(n.body,'$.corrects')=s.id) ORDER BY s.id""",
            (run["id"],),
        )
        if not rejected:
            return {"revised": 0, "supplementation": supplementation}
        items = []
        for i, s in enumerate(rejected, 1):
            card = json.loads(s["body"])
            support = rows(
                db,
                """SELECT e.quote,substr(v.body,max(1,e.start-160),e.end-e.start+320) context,w.title
                 FROM snapshot_evidence se JOIN evidence e ON se.evidence_id=e.id JOIN revisions v ON e.revision_id=v.id
                 JOIN documents d ON d.id=v.document_id LEFT JOIN works w ON w.id=d.work_id WHERE se.snapshot_id=?""",
                (s["id"],),
            )
            items.append(
                {
                    "id": "C" + str(i),
                    "card": card,
                    "problem": s["reason"],
                    "evidence": support,
                }
            )
    draft = await ask(
        "revise_unsupported",
        profile["strong_model"],
        "根据具体核对意见收窄措辞，修正已发生事实与未来计划的混淆。仅可用提供的引文。"
        "未来研究以可回答的问题、一个控制条件和互斥的观察结果表述。不许虚构指标、数字或已测过的设置。"
        "对暂缺条件的方向建议观察；尽量短，每个字段一到两句话。返回 {items:[{id,judgment,change,nearest,limitation,"
        "history_events:[按原顺序每个事件一条修正描述],hypothesis,horizon,confirm,refute,action:{kind,title,control,metric,stop,effort}}]}。",
        items,
        run["id"],
        max_tokens=4200,
    )
    answer = {v.get("id"): v for v in draft.get("items", [])}
    changed = 0
    for s, item in zip(rejected, items):
        edit = answer.get(item["id"])
        c = json.loads(s["body"])
        if not edit or len(edit.get("history_events", [])) != len(c["history"]):
            continue
        for field in ("judgment", "change", "nearest", "limitation"):
            c[field] = edit.get(field) or c[field]
        for h, new in zip(c["history"], edit["history_events"]):
            h["event"] = new
        for field in ("hypothesis", "horizon", "confirm", "refute"):
            c["forecast"][field] = edit[field]
        if isinstance(json.loads(s["body"]).get("nearest"), dict) and not isinstance(
            c["nearest"], dict
        ):
            c["nearest"] = json.loads(s["body"])["nearest"]
        c["action"] = edit["action"]
        c["corrects"] = s["id"]
        c["previous_snapshot"] = s["id"]
        c["new_evidence_ids"] = []
        with database() as db:
            papers, jobs = frozen_sources(db, s)
        eids, _ = validate_card(c, papers, jobs)
        refs = sorted(
            set(eids)
            | set((c.get("job_match") or {}).get("evidence_ids", []))
            | set(c.get("resource_evidence_ids") or [])
        )
        with database(write=True) as db:
            sig = key("review_revision", s["id"], c)
            sid = key(s["dir_id"], sig)
            when = now()
            db.execute(
                "INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    sid,
                    s["dir_id"],
                    run["id"],
                    when,
                    when,
                    run["profile_id"],
                    run["scope"],
                    s["rule_version"],
                    dump(c),
                    sig,
                ),
            )
            db.execute(
                "INSERT OR IGNORE INTO snapshot_reading_records SELECT ?,record_id FROM snapshot_reading_records WHERE snapshot_id=?",
                (sid, s["id"]),
            )
            for rel in c.get("evidence_relations") or []:
                db.executemany(
                    "INSERT OR IGNORE INTO direction_evidence_relations VALUES(?,?,?,?,?,?)",
                    (
                        (
                            sid,
                            rel["work_id"],
                            eid,
                            rel["assertion"],
                            rel["conditions"],
                            rel["relation"],
                        )
                        for eid in rel["evidence_ids"]
                    ),
                )
            for eid in refs:
                db.execute(
                    "INSERT OR IGNORE INTO snapshot_evidence VALUES(?,?)", (sid, eid)
                )
            for kind, statement, ids in [
                ("system_inference", c["judgment"], eids),
                (
                    "research_hypothesis",
                    c["forecast"]["hypothesis"],
                    c["forecast"]["evidence_ids"],
                ),
            ]:
                cid = claim(db, kind, statement, ids, refs, {"supersedes": s["id"]})
                db.execute(
                    "INSERT OR IGNORE INTO snapshot_claims VALUES(?,?)", (sid, cid)
                )
            put_values(
                db, sid, c, refs, activity(db, s["dir_id"], run["scope"], run["as_of"])
            )
            act = c["action"]
            db.execute(
                "INSERT OR IGNORE INTO actions VALUES(?,?,?,?,?,?,?)",
                (
                    key(sid, act["title"]),
                    sid,
                    act["title"],
                    act["kind"],
                    "proposed",
                    dump(act),
                    when,
                ),
            )
        changed += 1
    if changed:
        from .review import review

        await review(run)
    return {"revised": changed, "supplementation": supplementation}
