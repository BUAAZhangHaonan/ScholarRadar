import json
from typing import Literal
from fastapi import APIRouter
from pydantic import BaseModel,Field

from .db import database,rows
from .feedback import comparison,decision,feedback
from .factors import propose,transition

router=APIRouter()


class Decision(BaseModel):
    decision: Literal["accept","defer","reject","start","complete"]
    reason: str=Field("",max_length=2000)
    actual: dict=Field(default_factory=dict)
    request_id: str=Field(min_length=1,max_length=120)


class Feedback(BaseModel):
    entity_type: str
    entity_id: str
    dimension: str
    value: str
    reason: str=Field("",max_length=2000)
    request_id: str=Field(min_length=1,max_length=120)


@router.get("/api/actions")
def actions():
    with database() as db:
        items=rows(db,"SELECT a.*,s.dir_id FROM actions a JOIN snapshots s ON s.id=a.snapshot_id JOIN assessment_reviews r ON r.snapshot_id=s.id WHERE r.verdict='supported' OR a.status!='proposed' ORDER BY a.created_at DESC")
        for a in items:
            a["details"]=json.loads(a["details"])
            a["events"]=rows(db,"SELECT * FROM action_events WHERE action_id=? ORDER BY at",(a["id"],))
        return items


@router.post("/api/actions/{aid}/decision")
def decide(aid:str,data:Decision):
    with database(write=True) as db: return decision(db,aid,data.decision,data.reason,data.actual,data.request_id)


@router.post("/api/feedback")
def respond(data:Feedback):
    with database(write=True) as db: return feedback(db,**data.model_dump())


@router.get("/api/comparisons")
def comparisons():
    with database() as db: return comparison(db)


@router.get("/api/factors")
def factors():
    with database() as db:
        return {"definitions":rows(db,"SELECT * FROM factor_definitions"),"proposals":rows(db,"SELECT * FROM proposals")}


@router.post("/api/factors/proposals")
def proposal(definition:dict):
    with database(write=True) as db: return {"id":propose(db,definition)}


@router.post("/api/factors/proposals/{pid}/{state}")
def stage(pid:str,state:Literal["reviewed","shadow","active","retired"]):
    from .shadow import refresh,RULES
    with database(write=True) as db:
        if state in ("shadow","active"):
            row=db.execute("SELECT definition FROM proposals WHERE id=?",(pid,)).fetchone()
            if not row or json.loads(row[0]).get("method") not in RULES: raise ValueError("先注册可执行的因子规则")
        transition(db,pid,state)
        if state in ("shadow","active"): refresh(db)
    return {"status":state}

@router.get("/api/factors/shadow")
def shadow_results():
    with database() as db: return rows(db,"SELECT * FROM shadow_choices ORDER BY computed_at DESC")
