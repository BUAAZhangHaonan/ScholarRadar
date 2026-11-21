import json
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .access import install
from .db import database, rows
from .settings import ROOT
from .reader_api import direction_summaries, router as reader_router

app = FastAPI(title="ScholarRadar", docs_url=None, redoc_url=None, openapi_url=None)
install(app)
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")


@app.exception_handler(ValueError)
async def wrong_input(request: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)[:280]}, status_code=422)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
@app.get("/directions")
@app.get("/library")
@app.get("/actions")
@app.get("/settings")
def page():
    return FileResponse(ROOT / "web/index.html")


@app.get("/directions/{did}")
@app.get("/works/{did}")
@app.get("/tasks/{did}")
def reading_page(did: str):
    return page()


@app.get("/tasks")
@app.get("/maintenance")
def workspace_page():
    return page()


def one(db, sql, params=()):
    row = db.execute(sql, params).fetchone()
    if not row:
        raise HTTPException(404, "记录不存在")
    return dict(row)


@app.get("/api/daily")
def daily(
    date: date | None = None, kind: Literal["daily", "weekly", "monthly"] = "daily"
):
    with database() as db:
        clause = " AND as_of=?" if date else ""
        args = (kind, str(date)) if date else (kind,)
        row = db.execute(
            "SELECT body FROM reports WHERE kind=?"
            + clause
            + " ORDER BY as_of DESC,generated_at DESC LIMIT 1",
            args,
        ).fetchone()
        if not row:
            return {
                "kind": kind,
                "date": str(date) if date else None,
                "directions": [],
                "evidence": [],
                "coverage": {"sources": []},
                "pending": True,
            }
        return json.loads(row[0])


@app.get("/api/directions")
def directions(layer: str | None = None, status: str | None = None):
    with database() as db:
        return direction_summaries(db, layer, status)


@app.get("/api/directions/{did}")
def direction(did: str):
    with database() as db:
        row = one(db, "SELECT * FROM directions WHERE id=?", (did,))
        snapshots = rows(
            db,
            "SELECT * FROM snapshots WHERE dir_id=? ORDER BY generated_at DESC",
            (did,),
        )
        for s in snapshots:
            verdict = db.execute(
                "SELECT verdict,reason FROM assessment_reviews WHERE snapshot_id=?",
                (s["id"],),
            ).fetchone()
            s["review"] = (
                dict(verdict) if verdict else {"verdict": "pending", "reason": "待复核"}
            )
            s["body"] = json.loads(s["body"])
            s["factors"] = rows(
                db, "SELECT * FROM factor_values WHERE snapshot_id=?", (s["id"],)
            )
            for f in s["factors"]:
                f["value"] = json.loads(f["value"]) if f["value"] else None
                f["evidence_ids"] = json.loads(f["evidence_ids"])
        return {
            **row,
            "snapshots": snapshots,
            "relations": rows(
                db,
                "SELECT * FROM direction_relations WHERE from_id=? OR to_id=?",
                (did, did),
            ),
            "history_names": rows(
                db, "SELECT name,at FROM direction_names WHERE direction_id=?", (did,)
            ),
        }


from .library_api import router as library_router

app.include_router(library_router)
app.include_router(reader_router)

from .actions_api import router as actions_router

app.include_router(actions_router)

from .operations_api import router as operations_router

app.include_router(operations_router)

from .direction_api import router as direction_router

app.include_router(direction_router)

from .prestudy_api import router as prestudy_router

app.include_router(prestudy_router)
