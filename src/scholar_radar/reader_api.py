"""Reading projections built from published reports and reviewed direction snapshots."""
import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException

from .db import database, rows
from .reports import evidence_rows

router = APIRouter()


def follow_state(db, direction_id):
    latest = db.execute(
        """SELECT value FROM feedback WHERE entity_type='direction' AND entity_id=?
           AND dimension='follow' ORDER BY created_at DESC,rowid DESC LIMIT 1""",
        (direction_id,),
    ).fetchone()
    return bool(latest and latest[0] == "followed")


def materials(evidence):
    """One source per fixed revision; preserve each selectable citation."""
    groups = {}
    for item in evidence:
        source = item.get("revision_id") or item.get("url")
        if not source:
            continue
        group = groups.setdefault(source, {
            "work_id": item.get("work_id"), "title": item.get("title") or
            ("官方岗位详情" if item.get("kind") == "job" else "原始材料"),
            "url": item.get("url"), "kind": item.get("kind"), "version": item.get("version"),
            "citations": [],
        })
        if item.get("id") and item["id"] not in group["citations"]:
            group["citations"].append(item["id"])
    return list(groups.values())


def card_excerpt(db, direction_id, snapshot_id, card, evidence=None, action=None):
    if evidence is None:
        ids = [r[0] for r in db.execute(
            "SELECT evidence_id FROM snapshot_evidence WHERE snapshot_id=? ORDER BY rowid", (snapshot_id,)
        )]
        evidence = evidence_rows(db, ids)
    if action is None:
        a = db.execute(
            "SELECT id,title,kind,status FROM actions WHERE snapshot_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (snapshot_id,),
        ).fetchone()
        action = dict(a) if a else {}
    feasibility = card.get("feasibility") or {}
    if isinstance(feasibility, str):
        feasibility = {"asset": feasibility}
    proposed = card.get("action") or {}
    next_step = proposed.get("title") if isinstance(proposed, dict) else proposed
    return {
        "direction_id": direction_id, "snapshot_id": snapshot_id, "title": card.get("title"),
        "judgment": card.get("judgment"), "change": card.get("change"),
        "personal_fit": feasibility.get("asset"), "next_step": next_step or action.get("title"),
        "action_id": action.get("action_id") or action.get("id"), "action_state": action.get("status"),
        "materials": materials(evidence), "followed": follow_state(db, direction_id),
    }


def direction_summaries(db, layer=None, status=None):
    result = []
    directions = rows(db, """SELECT d.*,(SELECT count(*) FROM snapshots s WHERE s.dir_id=d.id) snapshot_count
        FROM directions d WHERE (? IS NULL OR d.layer=?) AND (? IS NULL OR d.status=? OR EXISTS
        (SELECT 1 FROM actions a JOIN snapshots s ON a.snapshot_id=s.id WHERE s.dir_id=d.id AND a.status=?))""",
        (layer, layer, status, status, status))
    for d in directions:
        snapshots = rows(db, """SELECT s.id,s.generated_at,s.body,r.verdict FROM snapshots s
            LEFT JOIN assessment_reviews r ON r.snapshot_id=s.id WHERE s.dir_id=?
            ORDER BY s.generated_at DESC,s.rowid DESC""", (d["id"],))
        approved = next((s for s in snapshots if s["verdict"] == "supported"), None)
        latest = snapshots[0] if snapshots else None
        projection = card_excerpt(db, d["id"], approved["id"], json.loads(approved["body"])) if approved else {}
        d.update(
            latest_snapshot_id=approved["id"] if approved else (latest["id"] if latest else None),
            latest_judgment=projection.get("judgment"), latest_change=projection.get("change"),
            latest_updated_at=latest["generated_at"] if latest else d["created_at"],
            personal_fit_summary=projection.get("personal_fit"), next_action=projection.get("next_step"),
            action_state=projection.get("action_state"), key_papers=projection.get("materials", []),
            followed=follow_state(db,d["id"]),
            review_state="supported" if approved else ("watch" if latest else "tracking"),
        )
        result.append(d)
    return sorted(result, key=lambda d: (
        d["action_state"] in {"active","accepted"},d["followed"],bool(d["latest_judgment"]),d["latest_updated_at"]
    ), reverse=True)


def project_report(db, kind, selected_date):
    clause = " AND as_of=?" if selected_date else ""
    args = (kind, str(selected_date)) if selected_date else (kind,)
    row = db.execute(
        "SELECT run_id,body FROM reports WHERE kind=?" + clause +
        " ORDER BY as_of DESC,generated_at DESC LIMIT 1", args
    ).fetchone()
    if row is None:
        pending = db.execute(
            "SELECT status FROM runs WHERE kind=?" + clause + " ORDER BY as_of DESC,created_at DESC LIMIT 1", args
        ).fetchone()
        return {"date":str(selected_date) if selected_date else None,"kind":kind,
                "state":"working" if pending and pending[0] in {"queued","running"} else "empty",
                "summary":None,"items":[],"watch":[],"readings":[],"proposal":None,"updates":[]}
    report = json.loads(row["body"])
    evidence = {e["id"]:e for e in report.get("evidence",[]) if e.get("id")}
    actions = {a.get("snapshot_id"):a for a in report.get("proposed_actions",[])}
    items=[]
    for snapshot in report.get("directions",[]):
        sid = snapshot["id"]
        relevant = [evidence[i] for i in snapshot.get("evidence_ids",[]) if i in evidence]
        items.append(card_excerpt(db,snapshot["direction_id"],sid,snapshot["card"],relevant,actions.get(sid)))
    review = report.get("review") or {}
    pick = review.get("proposal") or {}
    proposed = next((a for a in actions.values() if (a.get("action_id") or a.get("id"))==pick.get("action_id")),None)
    proposal = None
    if proposed:
        target = next((s for s in items if s["snapshot_id"]==proposed.get("snapshot_id")), {})
        proposal = {"title":proposed["title"],"why":pick.get("why"),"action_id":pick["action_id"],
                    "snapshot_id":proposed.get("snapshot_id"),"direction_id":target.get("direction_id"),
                    "details":proposed.get("details",{})}
    updates=report.get("research_updates")
    if updates is None:
        from .record_store import research_updates
        updates=research_updates(db,row["run_id"],limit=8) if kind=="daily" else []
        as_of=report.get("generated_at")
        if as_of:
            updates=[u for u in updates if db.execute("SELECT 1 FROM reading_records WHERE id=? AND recorded_at<=?",(u["record_id"],as_of)).fetchone()]
    used={m["work_id"] for item in items for m in item["materials"]}
    updates=[u for u in updates if u.get("work_id") not in used][:3]
    evolution=[{"direction_id":d.get("direction_id"),"title":d.get("title"),
                "nodes":[{"snapshot_id":n.get("snapshot_id"),"date":n.get("date"),"judgment":n.get("judgment"),
                          "change":n.get("change"),"verdict":n.get("verdict"),"evidence_ids":n.get("evidence_ids",[]),
                          "actions":n.get("actions",[]),"feedback":n.get("feedback",[])} for n in d.get("nodes",[])]}
               for d in report.get("evolution",[])]
    return {
        "date":report.get("date"), "kind":kind,"state":"published",
        "summary":review.get("summary") or (items[0]["judgment"] if items else None),
        "items":items,"watch":[{"direction_id":w.get("dir_id"),"snapshot_id":w.get("id"),"question":w.get("question")}
                              for w in report.get("watch",[]) if w.get("dir_id")],
        "readings":materials(evidence[i] for i in review.get("readings",[]) if i in evidence),
        "proposal":proposal,"updates":updates,"evolution":evolution,
    }


@router.get("/api/reading/report")
def reading_report(date: date | None = None, kind: Literal["daily","weekly","monthly"]="daily"):
    with database() as db:
        return project_report(db,kind,date)


@router.get("/api/reading/directions/{did}")
def direction_reading(did: str, snapshot: str | None = None):
    with database() as db:
        direction=db.execute("SELECT * FROM directions WHERE id=?", (did,)).fetchone()
        if not direction:
            raise HTTPException(404,"没有找到这个方向")
        snapshots=rows(db,"""SELECT s.id,s.generated_at,s.body,ar.verdict,ar.reason
            FROM snapshots s LEFT JOIN assessment_reviews ar ON ar.snapshot_id=s.id
            WHERE s.dir_id=? ORDER BY s.generated_at DESC,s.rowid DESC""",(did,))
        selected = next((s for s in snapshots if s["id"]==snapshot),None) if snapshot else next(
            (s for s in snapshots if s["verdict"]=="supported"), snapshots[0] if snapshots else None)
        if snapshot and not selected:
            raise HTTPException(404,"这个快照不属于当前方向")
        timeline=[]
        for s in snapshots:
            card=json.loads(s["body"])
            timeline.append({"snapshot_id":s["id"],"date":s["generated_at"],"verdict":s["verdict"],
                             "change":card.get("change") if s["verdict"]=="supported" else None,
                             "question":card.get("question"),"open_issue":s["reason"] if s["verdict"]!="supported" else None})
        current=None
        if selected:
            body=json.loads(selected["body"])
            current=card_excerpt(db,did,selected["id"],body)
            current.update(selected_at=selected["generated_at"],verdict=selected["verdict"],
                open_issue=selected["reason"] if selected["verdict"]!="supported" else None,
                history=body.get("history") or [],nearest=body.get("nearest"),
                feasibility=body.get("feasibility"),forecast=body.get("forecast"),
                career=body.get("job_match"),action=body.get("action"),resources=body.get("resources"),
                limitation=body.get("limitation"),method=body.get("method"),setting=body.get("setting"))
        return {**dict(direction),"current":current,"timeline":timeline,"followed":follow_state(db,did),
                "relations":rows(db,"SELECT * FROM direction_relations WHERE from_id=? OR to_id=?",(did,did))}


@router.get("/api/reading/works/{wid}")
def paper_reading(wid: str):
    from .record_store import work_records
    with database() as db:
        work=db.execute("SELECT title,metadata FROM works WHERE id=?",(wid,)).fetchone()
        if work is None:
            raise HTTPException(404,"没有找到这篇文献")
        metadata=json.loads(work["metadata"])
        records=work_records(db,wid)
        seen=set()
        readable=[]
        for rec in records:
            readable.append({k:rec[k] for k in ("id","revision_id","version","focus","heading","answer","sections","evidence_ids")})
            seen.update(rec["evidence_ids"])
        revision=db.execute("SELECT url FROM documents WHERE work_id=? AND kind='paper' ORDER BY rowid DESC LIMIT 1",(wid,)).fetchone()
        links=rows(db,"""SELECT r.url,r.kind,wr.relation FROM work_resources wr JOIN resources r ON r.id=wr.resource_id
                         WHERE wr.work_id=? ORDER BY r.url""",(wid,))
        related=rows(db,"""SELECT DISTINCT d.id,d.title,d.question FROM directions d JOIN memberships m
                       ON d.id=m.direction_id WHERE m.work_id=? AND d.status!='merged' ORDER BY d.title""",(wid,))
        return {"id":wid,"title":work["title"],"url":metadata.get("canonical_url") or (revision[0] if revision else None),
                "date":metadata.get("published_date") or metadata.get("year"),
                "abstract":metadata.get("abstract"),"records":readable,"resources":links,
                "directions":related,"evidence":evidence_rows(db,list(seen))}
