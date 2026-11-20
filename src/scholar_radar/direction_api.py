from typing import Literal
from fastapi import APIRouter
from pydantic import BaseModel, Field

from .db import database, key
from .settings import now

router = APIRouter()


class Change(BaseModel):
    operation: Literal["rename", "merge", "split"]
    target: str | None = None
    title: str | None = Field(None, max_length=220)
    question: str | None = None
    method: str | None = None
    setting: str | None = None


@router.post("/api/directions/{did}/changes")
def propose_change(did: str, data: Change):
    with database(write=True) as db:
        old = db.execute("SELECT * FROM directions WHERE id=?", (did,)).fetchone()
        if not old:
            raise ValueError("没有找到原方向")
        if data.operation == "rename":
            if not data.title or not data.title.strip():
                raise ValueError("请输入新名称")
            db.execute(
                "INSERT OR IGNORE INTO direction_names VALUES(?,?,?)",
                (did, old["title"], now()),
            )
            db.execute(
                "UPDATE directions SET title=? WHERE id=?", (data.title.strip(), did)
            )
            return {"id": did}
        target = data.target
        if data.operation == "split":
            if not all((data.title, data.question, data.method, data.setting)):
                raise ValueError("拆分需要具体问题、方法和评估场景")
            target = key("candidate", data.question, data.method, data.setting)
            db.execute(
                "INSERT OR IGNORE INTO directions VALUES(?,?,?,'candidate',?,?,?,'1',?)",
                (
                    target,
                    data.title,
                    old["layer"],
                    data.question,
                    data.method,
                    data.setting,
                    now(),
                ),
            )
        if (
            not target
            or target == did
            or not db.execute(
                "SELECT 1 FROM directions WHERE id=?", (target,)
            ).fetchone()
        ):
            raise ValueError("目标方向无效")
        ident = key("relation", did, target, data.operation)
        db.execute(
            "INSERT OR IGNORE INTO direction_relations VALUES(?,?,?,?,'proposed',?)",
            (ident, did, target, data.operation, now()),
        )
        return {"id": ident, "target": target, "status": "proposed"}


@router.post("/api/direction-changes/{ident}/confirm")
def confirm(ident: str):
    with database(write=True) as db:
        r = db.execute(
            "SELECT * FROM direction_relations WHERE id=?", (ident,)
        ).fetchone()
        if not r:
            raise ValueError("未找到分类调整")
        if r["status"] == "confirmed":
            return {"id": ident, "status": "confirmed"}
        if r["relation"] == "merge":
            db.execute(
                "UPDATE directions SET status='merged' WHERE id=?", (r["from_id"],)
            )
        db.execute(
            "UPDATE directions SET status='tracking',definition_version=CAST(CAST(definition_version AS INTEGER)+1 AS TEXT) WHERE id=?",
            (r["to_id"],),
        )
        db.execute(
            "UPDATE direction_relations SET status='confirmed',at=? WHERE id=?",
            (now(), ident),
        )
        # Membership in old snapshots remains historical; both windows need the new taxonomy.
        db.execute("UPDATE coverage SET classified=0 WHERE flow='observation'")
        return {"id": ident, "status": "confirmed"}
