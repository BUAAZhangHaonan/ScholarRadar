import json
from datetime import date, timedelta

from .db import rows
from .settings import dump, now

RULES = {"has_located_evidence", "linked_resource", "same_direction_work_count"}


def measure(db, rule, wid, cutoff):
    if rule == "has_located_evidence":
        sql = """SELECT EXISTS(SELECT 1 FROM evidence e JOIN revisions v ON v.id=e.revision_id JOIN documents d ON d.id=v.document_id
             JOIN factor_input_times t ON t.kind='evidence' AND t.entity=e.id WHERE d.work_id=? AND t.at<=?)"""
        return db.execute(sql, (wid, cutoff)).fetchone()[0]
    if rule == "linked_resource":
        return db.execute(
            "SELECT EXISTS(SELECT 1 FROM factor_input_times WHERE kind='resource' AND entity=? AND at<=?)",
            (wid, cutoff),
        ).fetchone()[0]
    if rule != "same_direction_work_count":
        raise ValueError("没有可执行的因子定义")
    return db.execute(
        """SELECT count(DISTINCT m2.work_id) FROM memberships m JOIN memberships m2 ON m.direction_id=m2.direction_id
          WHERE m.work_id=? AND m2.work_id!=m.work_id AND m.created_at<=? AND m2.created_at<=?""",
        (wid, cutoff, cutoff),
    ).fetchone()[0]


def active_signals(db, wid, cutoff):
    signals = {}
    for row in db.execute("SELECT definition FROM proposals WHERE lifecycle='active'"):
        spec = json.loads(row[0])
        if wid and spec["method"] in RULES:
            signals[spec["target"]] = measure(db, spec["method"], wid, cutoff)
    return signals


def refresh(db, run_id=None):
    sets = rows(
        db, "SELECT * FROM evaluations WHERE (? IS NULL OR run_id=?)", (run_id, run_id)
    )
    for p in db.execute(
        "SELECT * FROM proposals WHERE lifecycle IN ('shadow','active')"
    ):
        f = json.loads(p["definition"])
        rule = f.get("method")
        if rule not in RULES:
            continue
        for evaluation in sets:
            if db.execute(
                "SELECT 1 FROM shadow_choices WHERE proposal_id=? AND evaluation_id=?",
                (p["id"], evaluation["id"]),
            ).fetchone():
                continue
            candidates = json.loads(evaluation["candidates"])
            baseline = json.loads(evaluation["baseline"])
            cutoff = db.execute(
                "SELECT at FROM factor_input_times WHERE kind='evaluation' AND entity=?",
                (evaluation["id"],),
            ).fetchone()[0]
            score = {wid: measure(db, rule, wid, cutoff) for wid in candidates}
            positions = {wid: i for i, wid in enumerate(baseline)}
            ranked = sorted(
                candidates,
                key=lambda w: (-score[w], positions.get(w, len(candidates)), w),
            )
            due = date.fromisoformat(evaluation["as_of"]) + timedelta(
                days=int(f["window_days"])
            )
            db.execute(
                "INSERT INTO shadow_choices VALUES(?,?,?,?,?,?)",
                (
                    p["id"],
                    evaluation["id"],
                    dump(ranked[: len(baseline)]),
                    now(),
                    "pending" if len(set(score.values())) > 1 else "non_discriminating",
                    str(due),
                ),
            )


def disagreements(db, evaluation):
    alt = set(json.loads(evaluation["selected"]))
    for row in db.execute(
        "SELECT order_json FROM shadow_choices WHERE evaluation_id=? AND status!='non_discriminating'",
        (evaluation["id"],),
    ):
        alt.update(json.loads(row[0]))
    return set(json.loads(evaluation["baseline"])) ^ alt
