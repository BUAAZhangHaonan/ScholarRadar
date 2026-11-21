import json
from typing import Literal
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from .arc_bundle import selected_bundle
from .db import database,key,rows
from .queue import job
from .settings import ROOT,deployment,dump,now

router=APIRouter()


class Selection(BaseModel):
    snapshot_id: str=Field(min_length=1,max_length=128)
    stage: Literal["develop","run"]
    focus: str=Field(min_length=1,max_length=3000)
    idea_id: str|None=None
    request_id: str=Field(min_length=1,max_length=160)


def runtime():
    cfg=deployment().get("arc_runtime")
    if not cfg or any(not cfg.get(k) for k in ("executable","config","env_file","data_dir")):
        raise ValueError("ARC 部署路径尚未配置")
    return cfg


def enqueue_selection(db,did,selection):
    focus=selection.focus.strip()
    if not focus: raise ValueError("请写明本次希望查清的具体问题")
    if selection.idea_id:
        linked=db.execute("SELECT runtime_json FROM arc_handoffs WHERE direction_id=? AND idea_id=? AND status='completed' ORDER BY updated_at DESC LIMIT 1",(did,selection.idea_id)).fetchone()
        if not linked: raise ValueError("这个想法尚未在当前方向完成可承接的预研")
        cfg=json.loads(linked[0])
    else: cfg=runtime()
    hid,bundle=selected_bundle(db,did,selection.snapshot_id,selection.stage,focus,selection.idea_id)
    mapped=db.execute("SELECT handoff_id FROM arc_requests WHERE request_id=?",(selection.request_id,)).fetchone()
    if mapped and mapped[0]!=hid: raise ValueError("该提交编号已经用于另一项选题")
    old=db.execute("SELECT * FROM arc_handoffs WHERE id=?",(hid,)).fetchone()
    if not old:
        stamp=now(); rid=key("arc-stage",hid); profile=bundle["origin"]["profile_id"]
        db.execute("INSERT INTO runs(id,kind,as_of,profile_id,scope,status,created_at,detail) VALUES(?,'arc',?,?,?,'queued',?,?)",
            (rid,stamp[:10],profile,hid,stamp,dump({"handoff_id":hid,"stage":selection.stage})))
        jid=job(db,rid,"arc_stage",{"handoff_id":hid})
        db.execute("""INSERT INTO arc_handoffs(id,direction_id,snapshot_id,profile_id,stage,focus,idea_id,radar_run_id,job_id,
            status,bundle_json,runtime_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'queued',?,?,?,?)""",
            (hid,did,selection.snapshot_id,profile,selection.stage,focus,selection.idea_id,rid,jid,dump(bundle),dump(cfg),stamp,stamp))
    db.execute("INSERT OR IGNORE INTO arc_requests VALUES(?,?)",(selection.request_id,hid))
    row=db.execute("SELECT * FROM arc_handoffs WHERE id=?",(hid,)).fetchone()
    return {"id":hid,"task_id":row["job_id"],"run_id":row["radar_run_id"],"status":row["status"],"reused":bool(old)}


def present(row):
    obj={k:row[k] for k in ("id","direction_id","snapshot_id","profile_id","stage","focus","idea_id","arc_run_id","status","created_at","updated_at")}
    result=json.loads(row["result_json"] or "{}")
    obj.update({k:result.get(k) for k in ("execution_status","research_decision","evidence_limited","current_understanding",
                "next_question","presentation_status","presentation","draft","draft_text","cited_source_ids","previous_stage","source_mapping")})
    obj.update(direction_title=row["direction_title"],sources=result.get("source_directory",[]),error=row["error"])
    return obj


QUERY="SELECT h.*,d.title direction_title FROM arc_handoffs h JOIN directions d ON d.id=h.direction_id"


@router.post("/api/directions/{did}/prestudies",status_code=202)
def start(did:str,data:Selection):
    with database(write=True) as db: return enqueue_selection(db,did,data)


@router.get("/api/directions/{did}/prestudies")
def direction_tasks(did:str):
    with database() as db: return [present(r) for r in db.execute(QUERY+" WHERE direction_id=? ORDER BY h.created_at DESC",(did,))]


@router.get("/api/prestudies")
def tasks():
    with database() as db: return [present(r) for r in db.execute(QUERY+" ORDER BY h.created_at DESC LIMIT 80")]


@router.get("/api/prestudies/{hid}")
def task(hid:str):
    with database() as db: row=db.execute(QUERY+" WHERE h.id=?",(hid,)).fetchone()
    if not row: raise HTTPException(404,"预研任务不存在")
    return present(row)


@router.post("/api/prestudies/{hid}/resume",status_code=202)
def resume(hid:str):
    with database(write=True) as db:
        r=db.execute("SELECT * FROM arc_handoffs WHERE id=?",(hid,)).fetchone()
        if not r: raise HTTPException(404,"预研任务不存在")
        if r["status"] in ("connection_unknown","paused_external"):
            db.execute("UPDATE arc_handoffs SET status='queued',updated_at=? WHERE id=?",(now(),hid))
            db.execute("UPDATE jobs SET status='queued' WHERE id=?",(r["job_id"],))
            db.execute("UPDATE runs SET status='queued',ended_at=NULL WHERE id=?",(r["radar_run_id"],))
    return task(hid)
