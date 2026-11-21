import json
import re
from pathlib import Path

from .calls import invoke
from .db import database, key
from .evidence import arxiv_id, claim, resource, revision, span, work
from .record_store import save_record, work_records
from .settings import now

QUESTION = """根据当前可见段落解释论文。用中文的自然句回答，且在原文范围内给出逐字短引。
每个确有材料的部分另起一行，以「研究问题：」「关键机制：」「最近邻与比较：」「关键实验：」「适用条件：」「可复用部分：」「研究变化：」起句。
实验说明任务、对照、指标及结论的条件；文章自己的声明和已有独立验证要分别表达。
一个具体问题仍须查证时，在最后一行写「待补问题：」及需要什么实验、近邻或条件。没有原文依据的字段略去。"""

HEADINGS = {
    "evaluation": r"main results|experiments?|empirical results|evaluation|实[验証]|评估",
    "method": r"method|approach|framework|architecture|方法",
    "limits": r"limitations?|discussion|局限|讨论",
    "nearest": r"related work|prior work|background|相关工作|前作",
}


def passage(body, focus):
    """Select the named section through its next peer, capped at the service limit."""
    pattern=HEADINGS.get(focus)
    headings=list(re.finditer(r"(?m)^(#{1,6})[ \t]+(.{1,160})$",body))
    if pattern:
        for i,h in enumerate(headings):
            if re.search(pattern,h[2],re.I):
                end=next((n.start() for n in headings[i+1:] if len(n[1])<=len(h[1])),len(body))
                # Some parsers emit numbered subsections at the same Markdown level.
                section=re.match(r"(?:section\s+)?(\d+)\b",h[2],re.I)
                if section:
                    end=next((n.start() for n in headings[i+1:] if len(n[1])<=len(h[1])
                        and not re.match(r"^"+section[1]+r"\.\d",n[2])),len(body))
                return h.start(),min(64000,end-h.start()),h[2]
    intro=next((h for h in headings if re.search(r"\babstract\b|摘要",h[2],re.I)),None)
    start=intro.start() if intro else 0
    end=next((h.start() for h in headings if h.start()>start and re.search(r"related work|method|preliminar|相关工作|方法",h[2],re.I)),len(body))
    return start,min(64000,end-start),None


def outcome(record):
    return {"work_id":record["work_id"],"revision_id":record["revision_id"],"claim_id":record["id"],
            "record_id":record["id"],"analysis_id":record["analysis_id"],"version":record["version"],
            "evidence_ids":record["evidence_ids"],"coverage":record["coverage"]}


async def analyze_revision(wid,rid,focus,run_id,*,research_question=None,paper=None,required_heading=False):
    context=paper or {}
    focus=focus or "overview"
    with database() as db:
        rev=db.execute("""SELECT v.*,c.file FROM revisions v JOIN documents d ON d.id=v.document_id
             LEFT JOIN calls c ON c.id=v.source_call WHERE v.id=? AND d.work_id=? AND d.kind='paper'""",(rid,wid)).fetchone()
        if not rev: raise ValueError("缺少指定论文修订")
        existing=work_records(db,wid,rid)
    offset,size,heading=passage(rev["body"],focus)
    if required_heading and not heading: raise ValueError("当前固定修订没有匹配的章节标题")
    question=QUESTION
    if heading: question+=f"\n本次核对实际章节《{heading}》。"
    if research_question: question+="\n本次待澄清的问题："+research_question
    for record in existing:
        if required_heading and not (record["coverage"]["start"]<=offset and record["coverage"]["end"]>=offset+size):
            continue
        if record["focus"]==focus and (record["question"]==question or
              (not research_question and not record["sections"] and record["question"].startswith(("论文用什么方法","请核对当前原文章节")))):
            if run_id:
                with database(write=True) as db: db.execute("INSERT OR IGNORE INTO reading_record_runs VALUES(?,?)",(record["id"],run_id))
            return outcome(record)
    if not rev["file"]: raise ValueError("固定版本缺少原始读取收据")
    original=json.loads(Path(rev["file"]).read_text())
    if original["document_revision"]!=rev["upstream_revision"]: raise ValueError("原始读取收据与修订不一致")
    args={"document_id":original["document_id"],"question":question,"language":"zh","offset":offset,"limit_chars":size}
    identity=["record-v3",rid,rev["mode"],focus]
    result=await invoke("analysis","analyze_paper",args,identity=identity,id_field="analysis_id",run_id=run_id)
    if result.get("document_revision")!=rev["upstream_revision"] or result.get("document_id")!=args["document_id"]:
        raise ValueError("分析结果引用了另一份修订")
    analysis=result["analysis"]; cov=analysis.get("coverage") or {}
    start,end=cov.get("start"),cov.get("end")
    if not isinstance(start,int) or not isinstance(end,int) or not offset<=start<end<=offset+size:
        raise ValueError("分析缺少在请求区间内可核对的实际覆盖")
    with database(write=True) as db:
        eids=[]
        for item in analysis.get("evidence",[]):
            loc=next(iter(item.get("locations") or []),None)
            if loc:
                eids.append(span(db,rid,loc["start"],loc["end"],item["quote"]))
        if not eids: raise ValueError("精读结果没有可定位的支持证据")
        remote=result.get("analysis_id"); call_id=key("analysis","analyze_paper",identity,args)
        if remote!="radar-"+call_id: raise ValueError("分析服务返回的持久身份与原请求不符")
        cid=claim(db,"system_inference",analysis["answer"],eids,eids,
                  {"record_type":"paper_analysis","analysis_id":remote,"question":question,"coverage":cov,"model":analysis.get("model_used"),"revision":rid})
        for eid in eids:
            quote=db.execute("SELECT quote FROM evidence WHERE id=?",(eid,)).fetchone()[0]
            claim(db,"source_fact",quote,[eid],eids)
        created=save_record(db,wid=wid,rid=rid,cid=cid,analysis_id=remote,call_id=call_id,run_id=run_id,question=question,
             focus=focus,heading=heading,start=start,end=end,topic=context.get("theme_hint"),direction_ids=context.get("direction_ids") or [])
        if created:
            from .changes import invalidate
            explicit=[r[0] for r in db.execute("SELECT direction_id FROM reading_record_directions WHERE record_id=?",(cid,))]
            invalidate(db,"reading",wid,cid,explicit or None)
        db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
             (key(wid,"reading",rid),wid,"document_read",rev["version"],None,None,None,now(),now(),original.get("source",{}).get("original_url") or ""))
        return outcome(next(r for r in work_records(db,wid,rid) if r["id"]==cid))


async def read_paper(paper, run_id=None):
    if paper.get("target_revision_id") and paper.get("work_id"):
        return await analyze_revision(paper["work_id"],paper["target_revision_id"],paper.get("evidence_focus"),run_id,
             research_question=paper.get("analysis_question"),paper=paper,required_heading=True)
    aid, ver = arxiv_id(
        paper.get("arxiv_id")
        or str(paper.get("doi", "")).lower().removeprefix("10.48550/arxiv.")
    )
    query = (aid + ver) if aid else paper.get("doi")
    if not query and not paper.get("pdf_url"):
        raise ValueError("没有可读取的来源标识")
    args = {"query": query} if query else {"pdf_url": paper["pdf_url"]}
    args.update(offset=0, limit_chars=64000)
    first = await invoke(
        "analysis",
        "get_paper_text",
        args,
        identity=["read-v1", query or paper["pdf_url"]],
        run_id=run_id,
        safe=True,
    )
    doc, upstream = first["document_id"], first["document_revision"]
    parts = [first["markdown"]]
    end = first["range"]["end"]
    if first["range"]["start"] != 0 or len(parts[0]) != end:
        raise ValueError("起始范围不连续")
    while end < first["total_chars"]:
        part = await invoke(
            "analysis",
            "get_paper_text",
            {"document_id": doc, "offset": end, "limit_chars": 64000},
            identity=["slice", upstream, end],
            run_id=run_id,
            safe=True,
        )
        if (
            part["document_revision"] != upstream
            or part["mode"] != first["mode"]
            or part["range"]["start"] != end
            or part["range"]["end"] != end + len(part["markdown"])
            or not part["markdown"]
        ):
            raise ValueError("全文修订或连续区间发生变化")
        parts.append(part["markdown"])
        end = part["range"]["end"]
    body = "".join(parts)
    actual = first.get("paper") or {}
    base, exact = arxiv_id(actual.get("versioned_id") or doc)
    if ver and (exact != ver or base != aid):
        raise ValueError("实际取得的版本与请求版本不一致")
    ids = {
        "arxiv": base or aid,
        "doi": paper.get("doi"),
        "scholartrace": paper.get("paper_id"),
        "s2": paper.get("s2_id"),
        "openalex": paper.get("openalex_id"),
    }
    url = (
        ("https://arxiv.org/abs/" + base)
        if base
        else (first.get("source", {}).get("original_url") or paper.get("pdf_url") or "https://doi.org/" + query)
    )
    with database(write=True) as db:
        wid = work(db, paper["title"], ids, paper)
        src = key(
            "analysis",
            "get_paper_text",
            ["read-v1", query or paper.get("pdf_url")],
            args,
        )
        rid = revision(
            db,
            wid,
            url,
            "paper",
            upstream,
            body,
            version=exact or None,
            mode=first["mode"],
            source_call=src,
        )
        for link in re.findall(
            r"https?://(?:github\.com|huggingface\.co)/[\w.-]+/[\w.-]+", body
        ):
            resource(
                db,
                wid,
                link.rstrip("."),
                "official_link_candidate",
                "mentioned_in_document",
            )
    return await analyze_revision(wid,rid,paper.get("evidence_focus"),run_id,research_question=paper.get("analysis_question"),paper=paper)
