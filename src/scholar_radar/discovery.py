import asyncio
import json
from contextvars import ContextVar
from datetime import date, timedelta

from .calls import invoke
from .settings import ROOT


active_scope = ContextVar("active_source_scope", default=None)


def sources(version=None):
    from .db import database

    version = version or active_scope.get()
    with database() as db:
        if version:
            stored = db.execute(
                "SELECT body FROM scope_versions WHERE id=?", (version,)
            ).fetchone()
        else:
            stored = db.execute(
                "SELECT s.body FROM scope_activations a JOIN scope_versions s ON s.id=a.scope_id ORDER BY a.id DESC LIMIT 1"
            ).fetchone()
    return (
        json.loads(stored[0])
        if stored
        else json.loads((ROOT / "config/sources.json").read_text())
    )


def update_scope(db, topics, query):
    from .db import key
    from .settings import dump, now

    if (
        not 1 <= len(topics) <= 12
        or any(not 1 <= len(t.strip()) <= 350 for t in topics)
        or not 1 <= len(query.strip()) <= 1500
    ):
        raise ValueError("来源主题或观察范围无效")
    base = json.loads((ROOT / "config/sources.json").read_text())
    base.update(topics=topics, arxiv_query=query)
    ident = "scope-" + key(topics, query)[:12]
    base.update(scope_version=ident, query_version=ident)
    db.execute(
        "INSERT OR IGNORE INTO scope_versions VALUES(?,?,?)", (ident, now(), dump(base))
    )
    db.execute("INSERT INTO scope_activations(scope_id,at) VALUES(?,?)", (ident, now()))
    return base


async def discover_papers(day: date, cold: bool, run_id=None):
    cfg = sources()
    start = day - timedelta(days=90 if cold else 3)
    brief = (
        f"研究资料覆盖 {start} 至 {day}。寻找有原始论文、可定位方法或评估证据的独立作品。"
        + "；".join(cfg["topics"])
        + "。兼顾相关前作，区分发表日期与搜索日期。"
        "请优先提供 arXiv 外部标识与原始版本。选取具体相关研究，不要收录宽泛的行业新闻。"
    )
    args = {
        "theme_document": brief,
        "final_limit": 20 if cold else 5,
        "agent_candidate_limit": 60 if cold else 24,
        "include_rationale": True,
    }
    return await invoke(
        "trace",
        "query",
        args,
        identity=[cfg["query_version"], str(day), cold],
        id_field="request_id",
        run_id=run_id,
    )


async def official_page(url, day, run_id=None):
    return await invoke(
        "web",
        "fetch_page",
        {"url": url, "max_chars": 20000, "refresh": True},
        identity=["official", str(day), url],
        run_id=run_id,
        safe=True,
    )


if __name__ == "__main__":
    import sys
    from zoneinfo import ZoneInfo
    from datetime import datetime

    day = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if sys.argv[1:] == ["cold"]:
        result = asyncio.run(discover_papers(day, True))
        print(
            "ScholarTrace:",
            result.get("status"),
            len(result.get("papers", [])),
            flush=True,
        )
    elif sys.argv[1:] == ["official"]:
        result = asyncio.run(official_page(sources()["official_job"], day))
        print("web-research:", sorted(result), len(result.get("text", "")), flush=True)


async def discover_frontier(day, run_id):
    """One separate discovery budget per ISO week and source version."""
    cfg = sources()
    themes = cfg.get("frontier") or []
    if not themes:
        return None
    monday = day - timedelta(days=day.weekday())
    args = {
        "theme_document": f"{monday} 开始的一周：围绕 {'、'.join(themes)}，寻找有独立公开论文或评估资源的具体子问题。"
        + "说明与 "
        + "、".join(cfg["topics"])
        + " 中某项问题能怎样连接；大规模训练工作可仅供了解。",
        "final_limit": 3,
        "agent_candidate_limit": 18,
        "include_rationale": True,
    }
    return await invoke(
        "trace",
        "query",
        args,
        identity=["frontier-v1", cfg["query_version"], str(monday)],
        id_field="request_id",
        run_id=run_id,
    )
