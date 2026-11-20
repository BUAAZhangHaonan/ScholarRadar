from datetime import date
from urllib.parse import urlsplit
from .acquisition import coverage
from .db import database, key, rows
from .discovery import official_page
from .evidence import revision, span
from .settings import dump, now


async def verify_resources(run, limit=2):
    with database() as db:
        candidates = rows(
            db,
            """SELECT r.id,r.url,count(DISTINCT w.work_id) cited FROM resources r JOIN work_resources w ON r.id=w.resource_id
               LEFT JOIN resource_observations o ON o.resource_id=r.id
               WHERE r.url LIKE 'https://github.com/%' OR r.url LIKE 'https://huggingface.co/%'
               GROUP BY r.id ORDER BY (max(o.observed_at) IS NULL) DESC,max(o.observed_at),cited DESC,r.id LIMIT ?""",
            (limit,),
        )
    day = date.fromisoformat(run["as_of"])
    results = []
    for item in candidates:
        url = item["url"]
        try:
            page = await official_page(url, day, run["id"])
            actual = urlsplit(page.get("final_url") or url)
            body = page.get("text") or ""
            if not body or actual.hostname != urlsplit(url).hostname:
                raise ValueError("资源正文或最终域名未核实")
            with database(write=True) as db:
                source = key(
                    "web",
                    "fetch_page",
                    ["official", str(day), url],
                    {"url": url, "max_chars": 20000, "refresh": True},
                )
                rev = revision(
                    db,
                    None,
                    url,
                    "resource",
                    page["version"],
                    body,
                    total=page["total_chars"],
                    source_call=source,
                )
                desc = next(
                    (
                        s
                        for s in body.splitlines()
                        if 28 <= len(s.strip()) <= 400
                        and any(
                            v in s.lower()
                            for v in (
                                "dataset",
                                "model",
                                "code",
                                "benchmark",
                                "training",
                                "inference",
                                "evaluation",
                                "repository",
                            )
                        )
                    ),
                    None,
                )
                eid = (
                    span(db, rev, body.index(desc), body.index(desc) + len(desc), desc)
                    if desc
                    else None
                )
                db.execute(
                    "INSERT OR IGNORE INTO resource_observations VALUES(?,?,?,?,?,'accessible',?,?)",
                    (
                        key(item["id"], day.isoformat(), rev),
                        item["id"],
                        run["id"],
                        rev,
                        now(),
                        eid,
                        dump(
                            {
                                "title": page.get("title"),
                                "link_relation": "mentioned_in_document",
                                "replication_status": "not_run",
                            }
                        ),
                    ),
                )
                coverage(
                    db,
                    run["id"],
                    "官方资源",
                    "discovery",
                    run["scope"],
                    url,
                    day,
                    day,
                    1,
                    1,
                    "ok",
                    reason="已访问资源页，复现实验单独记录",
                )
            results.append(item["id"])
        except Exception as exc:
            with database(write=True) as db:
                db.execute(
                    "INSERT OR IGNORE INTO resource_observations VALUES(?,?,?,NULL,?,'unavailable',NULL,?)",
                    (
                        key(item["id"], str(day), "unavailable"),
                        item["id"],
                        run["id"],
                        now(),
                        dump({"reason": str(exc)[:180]}),
                    ),
                )
                coverage(
                    db,
                    run["id"],
                    "官方资源",
                    "discovery",
                    run["scope"],
                    url,
                    day,
                    day,
                    None,
                    None,
                    "unavailable",
                    reason=str(exc)[:180],
                )
    return {"verified": len(results)}
