import asyncio
import json
from datetime import date, timedelta

from .calls import invoke
from .settings import ROOT


def sources():
    return json.loads((ROOT / "config/sources.json").read_text())


async def discover_papers(day: date, cold: bool, run_id=None):
    cfg = sources()
    start = day - timedelta(days=90 if cold else 3)
    brief = (f"研究资料覆盖 {start} 至 {day}。寻找有原始论文、可定位方法或评估证据的独立作品。"
             + "；".join(cfg["topics"]) + "。兼顾相关前作，区分发表日期与搜索日期。"
             "请优先提供 arXiv 外部标识与原始版本。选取具体相关研究，不要收录宽泛的行业新闻。")
    args = {"theme_document":brief, "final_limit":20 if cold else 5,
            "agent_candidate_limit":60 if cold else 24, "include_rationale":True}
    return await invoke("trace","query",args,identity=[cfg["query_version"],str(day),cold],
                        id_field="request_id",run_id=run_id)


async def official_page(url, day, run_id=None):
    return await invoke("web","fetch_page",{"url":url,"max_chars":20000,"refresh":True},
                        identity=["official",str(day),url],run_id=run_id,safe=True)


if __name__ == "__main__":
    import sys
    from zoneinfo import ZoneInfo
    from datetime import datetime
    day = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if sys.argv[1:] == ["cold"]:
        result = asyncio.run(discover_papers(day,True))
        print("ScholarTrace:", result.get("status"),len(result.get("papers",[])),flush=True)
    elif sys.argv[1:] == ["official"]:
        result = asyncio.run(official_page(sources()["official_job"],day))
        print("web-research:", sorted(result),len(result.get("text","")),flush=True)
