import json
from .assessment import validate_card
from .gap_reading import fill_gaps
from .db import database, key, rows
from .evidence import claim
from .factors import activity, put_values
from .models import ask
from .profile import get_profile
from .settings import dump, now


async def revise(run):
    supplementation=await fill_gaps(run)
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
            return {"revised":0,"supplementation":supplementation}
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
        if isinstance(json.loads(s["body"]).get("nearest"),dict) and not isinstance(c["nearest"],dict):
            c["nearest"]=json.loads(s["body"])["nearest"]
        c["action"] = edit["action"]
        c["corrects"] = s["id"]
        c["previous_snapshot"] = s["id"]
        c["new_evidence_ids"] = []
        with database() as db:
            quotes=rows(db,"""SELECT e.id,e.quote,d.work_id,w.first_seen,w.metadata FROM snapshot_evidence se JOIN evidence e ON e.id=se.evidence_id
               JOIN revisions v ON v.id=e.revision_id JOIN documents d ON d.id=v.document_id LEFT JOIN works w ON w.id=d.work_id
               WHERE se.snapshot_id=?""",(s["id"],))
        papers={};jobs=[]
        for q in quotes:
            if q["work_id"]:
                meta=json.loads(q["metadata"])
                w=papers.setdefault(q["work_id"],{"quotes":{},"date":meta.get("published_date"),"year":meta.get("year"),"first_seen":q["first_seen"]})
                w["quotes"][q["id"]]=q["quote"]
            else: jobs.append(q)
        eids, _ = validate_card(c, papers, jobs)
        refs = sorted(
            set(eids) | set((c.get("job_match") or {}).get("evidence_ids", []))
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
            db.execute("INSERT OR IGNORE INTO snapshot_reading_records SELECT ?,record_id FROM snapshot_reading_records WHERE snapshot_id=?",(sid,s["id"]))
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
    return {"revised":changed,"supplementation":supplementation}
