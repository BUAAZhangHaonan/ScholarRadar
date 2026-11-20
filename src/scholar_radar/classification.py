import json
from .db import database, key, rows
from .models import ask
from .profile import get_profile
from .settings import dump, now


def taxonomy(db):
    catalog = rows(
        db,
        "SELECT id,question,method,setting,definition_version FROM directions WHERE status!='merged' ORDER BY id",
    )
    return key("observation-labels-v1", catalog), catalog


def covers(intervals, start, end):
    point = start
    for left, right in sorted(intervals):
        if right <= point:
            continue
        if left > point:
            return False
        point = max(point, right)
        if point >= end:
            return True
    return False


async def classify(run):
    with database() as db:
        version, catalog = taxonomy(db)
        profile = get_profile(db, run["profile_id"])
        docs = rows(
            db,
            """SELECT DISTINCT w.id,w.title,w.metadata FROM observed o JOIN works w ON w.id=o.work_id
               WHERE o.scope=? AND (o.membership_version IS NULL OR o.membership_version!=?) ORDER BY w.id""",
            (run["scope"], version),
        )
    for i in range(0, len(docs), 30):
        batch = docs[i : i + 30]
        request = [
            {
                "id": p["id"],
                "title": p["title"],
                "abstract": json.loads(p["metadata"]).get("abstract", "")[:400],
            }
            for p in batch
        ]
        result = await ask(
            "observation_classify",
            profile["fast_model"],
            "逐项根据研究问题、方法和场景归类。返回 {labels:[{id,directions:[方向id]}]}。不匹配填空数组，必须覆盖每一项，禁止新增标签。",
            {"directions": catalog, "works": request, "rule": version},
            run["id"],
        )
        labels = {v["id"]: v["directions"] for v in result["labels"]}
        if set(labels) != {v["id"] for v in batch}:
            raise ValueError("固定窗口归类未覆盖完整批次")
        allowed = {d["id"] for d in catalog}
        with database(write=True) as db:
            for wid, dids in labels.items():
                if not isinstance(dids, list) or not set(dids) <= allowed:
                    raise ValueError("未知的方向标签")
                for did in dids:
                    db.execute(
                        "INSERT OR IGNORE INTO memberships VALUES(?,?,?,?,?)",
                        (
                            did,
                            wid,
                            version,
                            dump({"source": "observation_classify"}),
                            now(),
                        ),
                    )
                db.execute(
                    "UPDATE observed SET membership_version=? WHERE scope=? AND work_id=?",
                    (version, run["scope"], wid),
                )
    with database(write=True) as db:
        db.execute(
            """UPDATE coverage SET classified=1 WHERE flow='observation' AND complete=1 AND scope=? AND NOT EXISTS
            (SELECT 1 FROM observed o WHERE o.scope=coverage.scope AND o.source=coverage.source AND o.event_time>=coverage.start
             AND o.event_time<coverage.end AND (o.membership_version IS NULL OR o.membership_version!=?))""",
            (run["scope"], version),
        )
    return version
