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
    from .shadow import active_signals
    from .db import database,rows
    from .settings import now
    from .recommendations import signals,paper_features
    with database() as db:
        taxonomy=rows(db,"SELECT id,question FROM directions WHERE status!='merged' ORDER BY id")
        feedback=signals(db,limit=10)
        labels={r["id"] for r in feedback}
        allowed_directions={d["id"] for d in taxonomy}
        cutoff=now()
        records=[{"id":ident,"title":p["title"],"abstract":p.get("abstract") or "",
                  "date":p.get("published_date") or p.get("year"),
                  "features":active_signals(db,p.get("work_id"),cutoff)} for ident,p in items.items()]
    latest={}
    for f in feedback:
        if f["entity_type"]=="work" and f["dimension"]=="reading_value":
            latest.setdefault(f["entity_id"],f)
    # A negative verdict on this exact paper is local to its unchanged material
    # and research profile. Other works, updated versions and time deferrals remain eligible.
    def unchanged_negative(p):
        f=latest.get(p.get("work_id"))
        return bool(f and f["value"]=="irrelevant" and (not f["profile_id"] or f["profile_id"]==profile["id"])
                    and f["features"].get("paper_signature")==paper_features(p)["paper_signature"])
    records=[r for r in records if not unchanged_negative(items[r["id"]])]
    admissible={r["id"] for r in records}
    if not records:return []
    # Constant features cannot distinguish candidates in this decision.
    variable={k for r in records for k in r["features"]
              if len({str(v["features"].get(k)) for v in records})>1}
    for row in records: row["features"]={k:v for k,v in row["features"].items() if k in variable}
    prompt=("从给定候选选出确实对当前问题有帮助的工作，细读完整摘要，不按标题热词选。"
        "结合明确评价过的对象与具体原因，区分支持、反例、限制和相邻机会。"
        "输出 {selected:[{id,reason,theme,evidence_focus,direction_ids,feedback_ids}]}。"
        "direction_ids 和 feedback_ids 只引用所给 ID，未使用则填空数组。"
        "evidence_focus 取 evaluation/method/limits。无相关材料返回空数组。")
    result=await ask("screen",profile["fast_model"],prompt,{"goals":profile["goals"],"exclude":profile["excluded_topics"],
                     "directions":taxonomy,"explicit_feedback":feedback,"limit":limit,"candidates":records},run_id)
    chosen=[]; seen=set()
    for item in result.get("selected",[]):
        ident=item.get("id")
        if ident not in admissible or ident in seen: continue
        seen.add(ident)
        chosen.append({**items[ident],"selection_reason":str(item.get("reason") or ""),
            "evidence_focus":item.get("evidence_focus") if item.get("evidence_focus") in ("method","evaluation","limits") else "evaluation",
            "theme_hint":item.get("theme"),"direction_ids":[d for d in (item.get("direction_ids") or []) if d in allowed_directions],
            "feedback_ids":[f for f in (item.get("feedback_ids") or []) if f in labels]})
        if len(chosen)>=limit: break
    return chosen
