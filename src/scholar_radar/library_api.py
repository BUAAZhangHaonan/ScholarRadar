import json
from fastapi import APIRouter, HTTPException, Query

from .db import database, rows
from .reports import evidence_rows

router = APIRouter()


@router.get("/api/library")
def library(
    kind: str = "all",
    q: str = Query("", max_length=200),
    limit: int = Query(40, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    pattern = "%" + q + "%"
    with database() as db:
        if kind == "code":
            return rows(
                db,
                "SELECT id,url AS title,url,kind FROM resources WHERE url LIKE ? ORDER BY rowid DESC LIMIT ? OFFSET ?",
                (pattern, limit, offset),
            )
        if kind == "team":
            return rows(
                db,
                "SELECT id,name AS title,'team' kind FROM organizations WHERE name LIKE ? ORDER BY name LIMIT ? OFFSET ?",
                (pattern, limit, offset),
            )
        if kind == "job":
            return rows(
                db,
                "SELECT id,title,url,'job' kind FROM postings WHERE title LIKE ? ORDER BY first_seen DESC LIMIT ? OFFSET ?",
                (pattern, limit, offset),
            )
        return rows(
            db,
            """SELECT w.id,w.title,'paper' kind,
             (SELECT count(*) FROM documents x JOIN revisions v ON v.document_id=x.id JOIN evidence e ON e.revision_id=v.id WHERE x.work_id=w.id) evidence_count,
             json_extract(w.metadata,'$.published_date') published FROM works w WHERE w.title LIKE ? OR
              (?!='' AND EXISTS(SELECT 1 FROM documents d JOIN revisions v ON v.document_id=d.id WHERE d.work_id=w.id AND v.body LIKE ?))
              ORDER BY (evidence_count>0) DESC,evidence_count DESC,w.first_seen DESC,w.id LIMIT ? OFFSET ?""",
            (pattern, q, pattern, limit, offset),
        )


@router.get("/api/works/{wid}")
def work_detail(wid: str):
    with database() as db:
        w = db.execute("SELECT * FROM works WHERE id=?", (wid,)).fetchone()
        if not w:
            raise HTTPException(404, "作品不存在")
        meta = json.loads(w["metadata"])
        docs = rows(
            db,
            """SELECT v.id,v.version,v.mode,v.total_chars,v.coverage,v.upstream_revision,d.url,v.observed_at
                        FROM documents d JOIN revisions v ON v.document_id=d.id WHERE d.work_id=?""",
            (wid,),
        )
        ids = [
            r[0]
            for r in db.execute(
                "SELECT e.id FROM evidence e JOIN revisions v ON v.id=e.revision_id JOIN documents d ON d.id=v.document_id WHERE d.work_id=?",
                (wid,),
            )
        ]
        return {
            "id": wid,
            "title": w["title"],
            "metadata": meta,
            "first_seen": w["first_seen"],
            "revisions": docs,
            "identifiers": rows(
                db, "SELECT namespace,value FROM identifiers WHERE work_id=?", (wid,)
            ),
            "resources": rows(
                db,
                "SELECT r.*,wr.relation FROM work_resources wr JOIN resources r ON r.id=wr.resource_id WHERE wr.work_id=?",
                (wid,),
            ),
            "evidence": evidence_rows(db, ids),
        }


@router.get("/api/evidence/{eid}")
def evidence_detail(eid: str):
    with database() as db:
        result = evidence_rows(db, [eid])
        if not result:
            raise HTTPException(404, "证据不存在")
        item = result[0]
        r = db.execute(
            "SELECT body,upstream_revision,coverage,total_chars,source_call FROM revisions WHERE id=?",
            (item["revision_id"],),
        ).fetchone()
        return {
            **item,
            "before": r["body"][max(0, item["start"] - 350) : item["start"]],
            "after": r["body"][item["end"] : item["end"] + 350],
            "document_revision": r["upstream_revision"],
            "coverage": json.loads(r["coverage"]),
            "total_chars": r["total_chars"],
            "source_call": r["source_call"],
            "claims": rows(
                db,
                "SELECT c.kind,c.statement FROM claim_evidence ce JOIN claims c ON c.id=ce.claim_id WHERE ce.evidence_id=?",
                (eid,),
            ),
        }


@router.get("/api/postings/{pid}")
def posting_detail(pid: str):
    with database() as db:
        r = db.execute("SELECT * FROM postings WHERE id=?", (pid,)).fetchone()
        if not r:
            raise HTTPException(404, "岗位不存在")
        hist = rows(
            db,
            "SELECT * FROM posting_observations WHERE posting_id=? ORDER BY verified_at DESC",
            (pid,),
        )
        for h in hist:
            h["details"] = json.loads(h["details"])
        return {**dict(r), "observations": hist}


from pydantic import BaseModel,Field


class SectionRequest(BaseModel):
    revision_id:str|None=None
    question:str|None=Field(None,max_length=1500)


@router.post("/api/works/{wid}/read-section/{focus}",status_code=202)
def read_section(wid:str,focus:str,data:SectionRequest|None=None):
    from .queue import job
    from .readings import passage
    from .changes import update_run,arrange
    if focus not in {"method","evaluation","limits"}: raise ValueError("未知章节类型")
    request=data or SectionRequest()
    with database(write=True) as db:
        row=db.execute("""SELECT l.run_id,l.work_key,v.id revision_id,v.body FROM readings l JOIN revisions v
            ON v.id=json_extract(l.outcome,'$.revision_id') WHERE json_extract(l.outcome,'$.work_id')=?
            AND l.status='done' AND (? IS NULL OR v.id=?) ORDER BY v.observed_at DESC,l.rowid DESC LIMIT 1""",
            (wid,request.revision_id,request.revision_id)).fetchone()
        if not row: raise ValueError("所选论文修订尚无可继续的精读记录")
        start,size,heading=passage(row["body"],focus)
        if not heading: raise ValueError("已解析全文没有匹配的章节标题")
        payload={"key":row["work_key"],"origin_run_id":row["run_id"],"focus":focus,"revision_id":row["revision_id"]}
        if request.question: payload["question"]=request.question
        # Reuse a previously queued exact request, including legacy section jobs.
        past=db.execute("""SELECT id,run_id FROM jobs WHERE stage='read' AND json_extract(payload,'$.focus')=?
             AND json_extract(payload,'$.revision_id')=? AND coalesce(json_extract(payload,'$.question'),'')=?
             ORDER BY rowid LIMIT 1""",(focus,row["revision_id"],request.question or "")).fetchone()
        if past: return {"job_id":past["id"],"run_id":past["run_id"],"heading":heading,"start":start,"end":start+size,"reused":True}
        rid=update_run(db)
        jid=job(db,rid,"read",payload);arrange(db,rid,("archive",))
        return {"job_id":jid,"run_id":rid,"heading":heading,"start":start,"end":start+size,"reused":False}
