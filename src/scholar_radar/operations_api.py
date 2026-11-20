import json
from datetime import date,datetime
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel

from .db import database,rows
from .profile import Profile,get_profile,save
from .queue import enqueue
from .reports import cost_summary
from .settings import VAR,ROOT

router=APIRouter()


class RunRequest(BaseModel):
    kind: Literal["daily","weekly","monthly"]="daily"
    day: date|None=None


@router.get("/api/profile")
def profile():
    with database() as db: return get_profile(db)


@router.put("/api/profile")
def update_profile(data:Profile):
    with database(write=True) as db: return {"id":save(db,data.model_dump())}


@router.get("/api/runs")
def runs():
    with database() as db:
        runs=rows(db,"SELECT * FROM runs ORDER BY created_at DESC LIMIT 60")
        for r in runs:
            r["cost"]=cost_summary(db,r["id"])
            r["jobs"]=rows(db,"SELECT stage,status,count(*) count FROM jobs WHERE run_id=? GROUP BY stage,status",(r["id"],))
        return runs


@router.get("/api/runs/{rid}")
def run(rid:str):
    with database() as db:
        found=db.execute("SELECT * FROM runs WHERE id=?",(rid,)).fetchone()
        if not found: raise HTTPException(404,"运行不存在")
        return {**dict(found),"jobs":rows(db,"SELECT stage,status,outcome,attempts FROM jobs WHERE run_id=?",(rid,)),
            "coverage":rows(db,"SELECT source,flow,status,reason,returned FROM coverage WHERE run_id=?",(rid,)),
            "calls":rows(db,"SELECT c.service,c.tool,c.status,c.remote_id,c.error,r.cached FROM calls c JOIN run_calls r ON r.call_id=c.id WHERE r.run_id=?",(rid,)),
            "cost":cost_summary(db,rid)}


@router.post("/api/runs",status_code=202)
def trigger(data:RunRequest):
    with database(write=True) as db:
        today=datetime.now(ZoneInfo(get_profile(db)["timezone"])).date()
        if data.day and data.day>today: raise ValueError("不能提前生成未来日期的报告")
        rid=enqueue(db,data.kind,data.day or today)
    return {"run_id":rid}


@router.get("/api/status")
def status():
    caps=json.loads((VAR/"capabilities.json").read_text()) if (VAR/"capabilities.json").exists() else {"services":{}}
    with database() as db:
        return {"services":{k:{"status":v["status"],"tools":[x["name"] for x in v.get("tools",[])],"version":v.get("version")} for k,v in caps["services"].items()},
          "inspected_at":caps.get("observed_at"),"cost":cost_summary(db),"archive":rows(db,"SELECT status,count(*) count FROM archives GROUP BY status"),
          "works":db.execute("SELECT count(*) FROM works").fetchone()[0],"evidence":db.execute("SELECT count(*) FROM evidence").fetchone()[0],
          "directions":db.execute("SELECT count(*) FROM directions").fetchone()[0],"readings":rows(db,"SELECT status,count(*) count FROM readings GROUP BY status")}


@router.get("/api/exports/internprep")
def internprep_export():
    with database() as db:
        r=db.execute("SELECT body FROM reports ORDER BY generated_at DESC LIMIT 1").fetchone()
        if not r: raise HTTPException(404,"尚无已发布快照")
        return json.loads(r[0])

@router.post("/api/runs/{rid}/resume")
def resume_run(rid:str):
    from .queue import resume
    with database(write=True) as db: return {"run_id":rid,"queued_stages":resume(db,rid)}
