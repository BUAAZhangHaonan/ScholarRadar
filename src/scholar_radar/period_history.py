import json
from datetime import datetime, time, timedelta, UTC
from zoneinfo import ZoneInfo
from .db import rows


def evolution(db, start, end, tz):
    beginning = (
        datetime.combine(start, time.min, ZoneInfo(tz)).astimezone(UTC).isoformat()
    )
    stop = (
        datetime.combine(end + timedelta(days=1), time.min, ZoneInfo(tz))
        .astimezone(UTC)
        .isoformat()
    )
    data = rows(
        db,
        """SELECT s.id,s.dir_id,s.body,s.generated_at,r.as_of,d.title,a.verdict,a.reason
        FROM snapshots s JOIN runs r ON r.id=s.run_id JOIN directions d ON d.id=s.dir_id
        LEFT JOIN assessment_reviews a ON a.snapshot_id=s.id WHERE r.as_of<=? ORDER BY r.as_of,s.generated_at,s.rowid""",
        (str(end),),
    )
    earlier = {}
    period = {}
    for x in data:
        b = json.loads(x["body"])
        refs = [
            v[0]
            for v in db.execute(
                "SELECT evidence_id FROM snapshot_evidence WHERE snapshot_id=?",
                (x["id"],),
            )
        ]
        node = {
            "snapshot_id": x["id"],
            "date": x["as_of"],
            "judgment": b.get("judgment"),
            "change": b.get("change"),
            "verdict": x["verdict"] or "pending",
            "open_issue": x["reason"] if x["verdict"] != "supported" else None,
            "evidence_ids": refs,
            "actions": [],
            "feedback": [],
        }
        if x["as_of"] < str(start):
            earlier[x["dir_id"]] = node
        else:
            period.setdefault(
                x["dir_id"],
                {"direction_id": x["dir_id"], "title": x["title"], "nodes": []},
            )["nodes"].append(node)
    decisions = rows(
        db,
        """SELECT a.snapshot_id,s.dir_id,d.title direction_title,a.title,ev.decision,ev.reason,ev.actual,ev.at FROM
        action_events ev JOIN actions a ON a.id=ev.action_id JOIN snapshots s ON s.id=a.snapshot_id JOIN directions d ON d.id=s.dir_id
        WHERE ev.at>=? AND ev.at<? ORDER BY ev.at""",
        (beginning, stop),
    )
    feedback = rows(
        db,
        """SELECT f.id,f.entity_type,f.entity_id,f.dimension,f.value,f.reason,f.created_at,c.snapshot_id,
        coalesce(s.dir_id,CASE WHEN f.entity_type='direction' THEN f.entity_id END) dir_id
        FROM feedback f JOIN feedback_contexts c ON c.feedback_id=f.id LEFT JOIN snapshots s ON s.id=c.snapshot_id
        WHERE f.created_at>=? AND f.created_at<?""",
        (beginning, stop),
    )
    for sample, field in [(decisions, "actions"), (feedback, "feedback")]:
        for record in sample:
            did = record["dir_id"]
            if not did:
                continue
            title = db.execute(
                "SELECT title FROM directions WHERE id=?", (did,)
            ).fetchone()
            g = period.setdefault(
                did,
                {"direction_id": did, "title": title[0] if title else did, "nodes": []},
            )
            node = next(
                (n for n in g["nodes"] if n["snapshot_id"] == record["snapshot_id"]),
                None,
            )
            if (
                node is None
                and did in earlier
                and earlier[did]["snapshot_id"] == record["snapshot_id"]
            ):
                node = earlier[did]
            if node is None:
                node = {
                    "snapshot_id": record["snapshot_id"],
                    "date": (record.get("at") or record.get("created_at"))[:10],
                    "verdict": "user_event",
                    "judgment": None,
                    "change": None,
                    "evidence_ids": [],
                    "actions": [],
                    "feedback": [],
                }
                g["nodes"].append(node)
            node[field].append(record)
    for did, g in period.items():
        if did in earlier:
            g["nodes"].insert(0, {**earlier[did], "baseline": True})
    return list(period.values())
