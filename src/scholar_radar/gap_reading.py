"""Resolve one concrete review evidence question before another scientific assessment."""
import json

from . import changes
from .calls import invoke
from .db import database,rows
from .models import ask
from .profile import get_profile
from .readings import analyze_revision,read_paper
from .record_store import work_records
from .settings import dump


async def read_neighbor(run,gap):
    hints=json.loads(gap["details"]); requested=str(hints.get("neighbor") or "").strip()
    with database() as db:
        profile=get_profile(db,run["profile_id"])
        row=db.execute("""SELECT DISTINCT w.id FROM works w LEFT JOIN identifiers x ON x.work_id=w.id
            WHERE lower(w.title)=lower(?) OR lower(x.value)=lower(?) ORDER BY w.id LIMIT 2""",(requested,requested)).fetchall() if requested else []
        old=work_records(db,row[0][0]) if len(row)==1 else []
    if old:
        target=old[0]
        return await analyze_revision(target["work_id"],target["revision_id"],"evaluation",run["id"],
               research_question=gap["question"],paper={"direction_ids":[gap["direction_id"]]})
    brief="围绕一个待核查的最近邻查找原始研究。问题："+gap["question"]
    if requested: brief+="\n已有论文线索："+requested
    data=await invoke("trace","query",{"theme_document":brief,"final_limit":3,"agent_candidate_limit":15,"include_rationale":True},
                      id_field="request_id",identity=["review-neighbor-v1",gap["id"]],run_id=run["id"])
    candidates=[p for p in data.get("papers",[]) if p.get("arxiv_id") or p.get("doi") or p.get("pdf_url")]
    if not candidates: raise ValueError("近邻检索没有返回可核查原文的研究")
    options={f"P{i}":p for i,p in enumerate(candidates,1)}
    selection=await ask("select_gap_neighbor",profile["fast_model"],
        "选择真正能回答该具体比较的一篇论文。用完整摘要判断，题名近似不等于同一工作。返回 {id,reason}，没有合适材料时 id=null。",
        {"question":gap["question"],"requested":requested,"papers":[{"id":i,"title":p["title"],"abstract":p.get("abstract")} for i,p in options.items()]},
        run["id"],max_tokens=750)
    choice=options.get(selection.get("id"))
    if not choice: raise ValueError("已检索的近邻未回答这个具体比较")
    return await read_paper({**choice,"analysis_question":gap["question"],"evidence_focus":"evaluation",
                           "direction_ids":[gap["direction_id"]]},run["id"])


async def fill_gaps(run):
    attempted=0; completed=[]
    with database() as db:
        gaps=rows(db,"""SELECT g.* FROM research_gaps g JOIN snapshots s ON s.id=g.snapshot_id
             WHERE s.run_id=? AND g.status IN ('open','running') AND g.kind IN ('experiment','method','conditions','neighbor')
             AND json_extract(s.body,'$.corrects') IS NULL ORDER BY g.rowid""",(run["id"],))
    for g in gaps:
        with database(write=True) as db:
            # One directed supplemental reading per direction for this run.
            used=db.execute("""SELECT 1 FROM research_gaps g JOIN snapshots s ON g.snapshot_id=s.id
                 WHERE s.run_id=? AND g.direction_id=? AND g.id!=? AND g.status IN ('filled','blocked','running') LIMIT 1""",
                 (run["id"],g["direction_id"],g["id"])).fetchone()
            if used: continue
            db.execute("UPDATE research_gaps SET status='running' WHERE id=?",(g["id"],))
        attempted+=1
        try:
            if g["kind"]=="neighbor":
                out=await read_neighbor(run,g)
            else:
                focus={"experiment":"evaluation","method":"method","conditions":"limits"}[g["kind"]]
                out=await analyze_revision(g["work_id"],g["revision_id"],focus,run["id"],research_question=g["question"],
                         paper={"direction_ids":[g["direction_id"]]},required_heading=True)
        except Exception as exc:
            detail={**json.loads(g["details"]),"barrier":str(exc)[:300]}
            with database(write=True) as db:
                db.execute("UPDATE research_gaps SET status='blocked',details=? WHERE id=?",(dump(detail),g["id"]))
            continue
        with database(write=True) as db:
            db.execute("UPDATE research_gaps SET status='filled',record_id=? WHERE id=?",(out["record_id"],g["id"]))
            db.execute("INSERT OR IGNORE INTO reading_record_directions VALUES(?,?,'review_gap')",(out["record_id"],g["direction_id"]))
            changes.invalidate(db,"reading",out["work_id"],out["record_id"],[g["direction_id"]])
        completed.append(g["id"])
    return {"attempted":attempted,"filled":completed}
