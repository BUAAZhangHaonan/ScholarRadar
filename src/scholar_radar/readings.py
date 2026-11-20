import asyncio
import json
import re

from .calls import invoke
from .db import database, key
from .evidence import arxiv_id, claim, resource, revision, span, work
from .settings import dump, now

QUESTION = ("论文用什么方法解决哪个具体问题？分别说明实际评估任务、对照、一个关键证据和适用条件。"
            "只选1至3个5至15词的连续原文短语，保留原大小写和标点，一字不改，逐句贴合所读片段。局部文本未覆盖的事项留空。")


async def read_paper(paper, run_id=None):
    aid, ver = arxiv_id(paper.get("arxiv_id") or str(paper.get("doi","")).lower().removeprefix("10.48550/arxiv."))
    query = (aid + ver) if aid else paper.get("doi")
    if not query and not paper.get("pdf_url"):
        raise ValueError("没有可读取的来源标识")
    args = {"query":query} if query else {"pdf_url":paper["pdf_url"]}
    args.update(offset=0,limit_chars=64000)
    first = await invoke("analysis","get_paper_text",args,identity=["read-v1",query or paper["pdf_url"]],run_id=run_id,safe=True)
    doc, upstream = first["document_id"],first["document_revision"]
    parts=[first["markdown"]]
    end = first["range"]["end"]
    if first["range"]["start"]!=0 or len(parts[0])!=end:
        raise ValueError("起始范围不连续")
    while end < first["total_chars"]:
        part = await invoke("analysis","get_paper_text",{"document_id":doc,"offset":end,"limit_chars":64000},
                            identity=["slice",upstream,end],run_id=run_id,safe=True)
        if (part["document_revision"]!=upstream or part["mode"]!=first["mode"] or
            part["range"]["start"]!=end or part["range"]["end"]!=end+len(part["markdown"]) or not part["markdown"]):
            raise ValueError("全文修订或连续区间发生变化")
        parts.append(part["markdown"])
        end=part["range"]["end"]
    body="".join(parts)
    actual=first.get("paper") or {}
    base, exact=arxiv_id(actual.get("versioned_id") or doc)
    if ver and (exact!=ver or base!=aid):
        raise ValueError("实际取得的版本与请求版本不一致")
    ids={"arxiv":base or aid,"doi":paper.get("doi"),"scholartrace":paper.get("paper_id"),
         "s2":paper.get("s2_id"),"openalex":paper.get("openalex_id")}
    url=("https://arxiv.org/abs/"+base) if base else (first.get("source",{}).get("original_url") or "https://doi.org/"+query)
    with database(write=True) as db:
        wid=work(db,paper["title"],ids,paper)
        src=key("analysis","get_paper_text",["read-v1",query or paper.get("pdf_url")],args)
        rid=revision(db,wid,url,"paper",upstream,body,version=exact or None,mode=first["mode"],source_call=src)
        for link in re.findall(r'https?://(?:github\.com|huggingface\.co)/[\w.-]+/[\w.-]+',body):
            resource(db,wid,link.rstrip("."),"official_link_candidate","mentioned_in_document")
    focus={"document_id":doc,"question":QUESTION,"language":"zh","offset":0,"limit_chars":min(11500,len(body))}
    result=await invoke("analysis","analyze_paper",focus,identity=["question-v2",upstream,first["mode"]],
                        id_field="analysis_id",run_id=run_id)
    if result["document_revision"]!=upstream:
        raise ValueError("分析结果引用了另一份修订")
    analysis=result["analysis"]
    with database(write=True) as db:
        evidence=[]
        for item in analysis.get("evidence",[]):
            if not item.get("locations"):
                continue
            loc=item["locations"][0]
            evidence.append(span(db,rid,loc["start"],loc["end"],item["quote"]))
        if not evidence:
            raise ValueError("精读结果没有可定位的支持证据")
        cid=claim(db,"system_inference",analysis["answer"],evidence,evidence,{"question":QUESTION,
                  "coverage":analysis.get("coverage"),"model":analysis.get("model_used"),"revision":rid})
        for eid in evidence:
            text=db.execute("SELECT quote FROM evidence WHERE id=?",(eid,)).fetchone()[0]
            claim(db,"source_fact",text,[eid],evidence)
        db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (key(wid,"reading",upstream),wid,"document_read",exact or None,None,None,None,now(),now(),url))
    return {"work_id":wid,"revision_id":rid,"claim_id":cid,"evidence_ids":evidence,"version":exact or None}
