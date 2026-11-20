"""Date-bounded supplementary discovery for material missing from ranked search."""

import asyncio
from datetime import timedelta
import httpx

from .calls import invoke
from .db import key
from .models import ask
from .settings import deployment

QUERIES = (
    '"hallucination" + ("multimodal" | "vision-language" | "visual reasoning")',
    '("tool use" | "tool calling" | "instruction following" | "selective prediction") + ("language models" | "LLM" | "agents")',
)
DATE_FIELDS = "title,abstract,externalIds,publicationDate,authors,url,openAccessPdf"


async def fetch_page(args):
    config = deployment()
    headers = {"x-api-key": config["s2_key"]} if config.get("s2_key") else {}
    async with httpx.AsyncClient(timeout=35, follow_redirects=True) as client:
        r = await client.get(
            "https://api.semanticscholar.org/graph/v1/paper/search/bulk",
            params=args,
            headers=headers,
        )
        if r.is_error:
            return {"error": "Semantic Scholar HTTP " + str(r.status_code)}
        result = r.json()
    result["cost"] = {
        "basis": "no_paid_calls",
        "currency": "CNY",
        "total_cny": 0,
        "lower_cny": 0,
        "upper_cny": 0,
    }
    return result


async def recent_candidates(day, cold, run_id=None):
    start = day - timedelta(days=90 if cold else 3)
    found = {}
    batches = []
    for query in QUERIES:
        args = {
            "query": query,
            "publicationDateOrYear": f"{start}:{day}",
            "fields": DATE_FIELDS,
            "sort": "publicationDate:desc",
        }
        page = await invoke(
            "s2",
            "paper_search_bulk",
            args,
            identity=["date-discovery-v1", str(day), cold],
            run_id=run_id,
            transport=fetch_page,
            safe=True,
        )
        items = page.get("data", [])
        batches.append(
            {
                "query": query,
                "start": str(start),
                "end": str(day),
                "returned": len(items),
                "truncated": bool(page.get("token")),
                "total_estimate": page.get("total"),
                "call_id": key(
                    "s2",
                    "paper_search_bulk",
                    ["date-discovery-v1", str(day), cold],
                    args,
                ),
            }
        )
        for p in items:
            ids = p.get("externalIds") or {}
            if not (ids.get("ArXiv") or ids.get("DOI")) or not p.get("publicationDate"):
                continue
            found[p["paperId"]] = {
                "title": p["title"],
                "abstract": p.get("abstract") or "",
                "arxiv_id": ids.get("ArXiv"),
                "doi": ids.get("DOI"),
                "s2_id": p["paperId"],
                "published_date": p["publicationDate"],
                "authors": [x["name"] for x in p.get("authors", [])],
                "canonical_url": (
                    "https://arxiv.org/abs/" + ids["ArXiv"]
                    if ids.get("ArXiv")
                    else "https://doi.org/" + ids["DOI"]
                ),
                "pdf_url": (p.get("openAccessPdf") or {}).get("url"),
                "discovery_source": "s2",
            }
        await asyncio.sleep(1.1)
    return list(found.values()), batches


def external_key(p):
    return (
        (p.get("arxiv_id") or p.get("doi") or p.get("s2_id") or p.get("paper_id"))
        .lower()
        .removeprefix("10.48550/arxiv.")
    )


async def shortlist(papers, profile, limit, run_id=None):
    if not papers:
        return []
    items = {external_key(p): p for p in papers}
    words = (
        "hallucinat",
        "constraint",
        "instruction",
        "tool",
        "abstention",
        "representation",
        "selective",
        "agent",
        "calibrat",
        "conflict",
        "before",
        "uncertaint",
    )

    def priority(pair):
        p = pair[1]
        return (
            sum(w in p["title"].lower() for w in words),
            bool(p.get("arxiv_id")),
            p.get("published_date") or "",
        )

    subset = dict(sorted(items.items(), key=priority, reverse=True)[:85])
    records = [
        {
            "id": i,
            "title": p["title"],
            "abstract": (p.get("abstract") or "")[:450],
            "date": p.get("published_date"),
        }
        for i, p in subset.items()
    ]
    from .shadow import active_signals
    from .db import database
    from .settings import now

    with database() as db:
        if db.execute(
            "SELECT 1 FROM proposals WHERE lifecycle='active' LIMIT 1"
        ).fetchone():
            cutoff = now()
            for row in records:
                row["active_factors"] = active_signals(
                    db, subset[row["id"]].get("work_id"), cutoff
                )
    instr = (
        "从本次真实候选选出与研究问题最贴近、具有具体实验或可复用资源的材料。排除领域只可作为旁证。"
        "输出 {selected:[{id,reason,theme,evidence_focus}]}，id必须来自候选。按问题选择 evidence_focus：evaluation、method 或 limits。保留少量相邻和方法上不同的材料，"
        "根据候选质量决定是否选满，不选重复工作。"
    )
    result = await ask(
        "screen",
        profile["fast_model"],
        instr,
        {
            "goals": profile["goals"],
            "exclude": profile["excluded_topics"],
            "limit": limit,
            "candidates": records,
        },
        run_id,
    )
    chosen = []
    seen = set()
    for x in result.get("selected", []):
        i = x.get("id")
        if i not in subset or i in seen:
            continue
        seen.add(i)
        chosen.append(
            {
                **subset[i],
                "selection_reason": x.get("reason"),
                "evidence_focus": x.get("evidence_focus", "evaluation"),
                "theme_hint": x.get("theme"),
            }
        )
        if len(chosen) >= limit:
            break
    return chosen
