from .db import key
from .settings import dump, now

STATES = {
    "proposed": {"accept": "accepted", "defer": "deferred", "reject": "rejected"},
    "deferred": {"accept": "accepted", "reject": "rejected"},
    "accepted": {"start": "active", "defer": "deferred", "reject": "rejected"},
    "active": {"complete": "completed", "defer": "deferred"},
}
VALUES = {
    "reading_status": {"unread", "read", "known"},
    "reading_value": {"useful", "average", "irrelevant"},
    "career_value": {"verified", "helpful", "artifact", "irrelevant"},
    "comparison": {"read", "try", "skip"},
}
TARGETS = {
    "work": "works",
    "direction": "directions",
    "action": "actions",
    "evaluation": "evaluations",
    "evidence": "evidence",
}


def decision(db, aid, choice, reason, actual, request_id):
    eid = key("decision", aid, request_id)
    old = db.execute("SELECT decision FROM action_events WHERE id=?", (eid,)).fetchone()
    if old:
        return {"id": aid, "status": old[0]}
    row = db.execute("SELECT status,kind FROM actions WHERE id=?", (aid,)).fetchone()
    if not row:
        raise ValueError("行动不存在")
    new = STATES.get(row["status"], {}).get(choice)
    if not new:
        raise ValueError("此行动当前状态不支持该操作")
    if new == "active" and row["kind"] == "verify":
        from .profile import get_profile

        active = db.execute(
            "SELECT count(*) FROM actions WHERE status='active' AND kind='verify'"
        ).fetchone()[0]
        if active >= get_profile(db)["active_limit"]:
            raise ValueError("已达到同时验证数")
    db.execute("UPDATE actions SET status=? WHERE id=?", (new, aid))
    db.execute(
        "INSERT INTO action_events VALUES(?,?,?,?,?,?,?)",
        (eid, aid, row["status"], new, reason, dump(actual), now()),
    )
    return {"id": aid, "status": new}


def feedback(db, entity_type, entity_id, dimension, value, reason, request_id):
    table = TARGETS.get(entity_type)
    if (
        not table
        or not db.execute(
            "SELECT 1 FROM " + table + " WHERE id=?", (entity_id,)
        ).fetchone()
    ):
        raise ValueError("反馈对象不存在")
    if value not in VALUES.get(dimension, set()):
        raise ValueError("反馈选项无效")
    fid = key("feedback", entity_type, entity_id, request_id)
    db.execute(
        "INSERT OR IGNORE INTO feedback VALUES(?,?,?,?,?,?,?)",
        (fid, entity_type, entity_id, dimension, value, reason, now()),
    )
    return {"id": fid}


def comparison(db):
    r = db.execute(
        "SELECT * FROM evaluations ORDER BY as_of DESC,rowid DESC LIMIT 1"
    ).fetchone()
    if not r:
        return []
    from .shadow import disagreements

    diff = disagreements(db, r)
    result = []
    for wid in sorted(diff, key=lambda x: key(r["id"], x)):
        seen = db.execute(
            "SELECT 1 FROM feedback WHERE entity_type='work' AND entity_id=? AND dimension='comparison'",
            (wid,),
        ).fetchone()
        if seen:
            continue
        w = db.execute("SELECT title FROM works WHERE id=?", (wid,)).fetchone()
        if w:
            result.append({"work_id": wid, "title": w[0]})
        if len(result) == 3:
            break
    return result
