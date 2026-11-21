"""Keep what a user saw, their explicit judgement and later outcomes together."""
import json
from .db import key,rows
from .settings import dump,now


def record(db,kind,entity,why,features,*,pid=None,sid=None,evaluation=None,origin="reading",used=(),at=None):
    rid=key("recommendation",kind,entity,sid,evaluation,origin,why,features,sorted(used))
    db.execute("INSERT OR IGNORE INTO recommendation_contexts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (rid,kind,entity,sid,evaluation,pid,at or now(),origin,why,dump(features),dump(sorted(used))))
    return rid


def paper_features(p):
    return {"paper_signature":key(p.get("title"),p.get("abstract") or "",p.get("arxiv_id"),p.get("doi"),p.get("published_date"),p.get("version")),"title":p.get("title"),"published":p.get("published_date") or p.get("year"),
            "abstract":p.get("abstract") or "", "public_locator":bool(p.get("arxiv_id") or p.get("pdf_url")),
            "research_questions":p.get("direction_ids") or [],"topic":p.get("theme_hint") or ""}


def context_for(db,kind,entity,snapshot_id=None):
    if kind=="direction":
        sql="SELECT s.* FROM snapshots s WHERE s.dir_id=?"
        args=[entity]
        if snapshot_id: sql+=" AND s.id=?"; args.append(snapshot_id)
        s=db.execute(sql+" ORDER BY s.generated_at DESC,s.rowid DESC LIMIT 1",args).fetchone()
        if snapshot_id and not s: raise ValueError("反馈与所选方向快照不匹配")
        if s:
            body=json.loads(s["body"])
            return record(db,kind,entity,body.get("change") or body.get("judgment",""),
                       {"title":body.get("title"),"judgment":body.get("judgment"),"next_action":body.get("action"),
                        "personal_connection":body.get("feasibility"),"work_ids":body.get("work_ids",[])},
                       pid=s["profile_id"],sid=s["id"],origin="direction",at=s["generated_at"])
    if kind=="work":
        existing=db.execute("SELECT id FROM recommendation_contexts WHERE entity_type='work' AND entity_id=? AND origin IN ('screen','baseline') ORDER BY recorded_at DESC,CASE origin WHEN 'screen' THEN 0 ELSE 1 END,rowid DESC LIMIT 1",(entity,)).fetchone()
        if existing:return existing[0]
        last=db.execute("""SELECT l.paper,e.id evaluation,e.as_of,r.profile_id,r.created_at FROM readings l
            JOIN runs r ON r.id=l.run_id LEFT JOIN evaluations e ON e.run_id=r.id
            WHERE json_extract(l.paper,'$.work_id')=? ORDER BY r.created_at DESC LIMIT 1""",(entity,)).fetchone()
        if last:
            p=json.loads(last["paper"])
            return record(db,kind,entity,p.get("selection_reason") or p.get("rationale") or "",
                paper_features(p),pid=last["profile_id"],evaluation=last["evaluation"],origin="screen",
                used=p.get("feedback_ids",[]),at=last["created_at"])
        row=db.execute("SELECT title,metadata FROM works WHERE id=?",(entity,)).fetchone()
        if row: return record(db,kind,entity,"",paper_features({**json.loads(row["metadata"]),"title":row["title"]}),origin="library")
    return None


def bind(db,fid,kind,entity,recommendation=None,snapshot=None,action=None):
    if db.execute("SELECT 1 FROM feedback_contexts WHERE feedback_id=?",(fid,)).fetchone(): return
    if recommendation:
        rec=db.execute("SELECT * FROM recommendation_contexts WHERE id=? AND entity_type=? AND entity_id=?",(recommendation,kind,entity)).fetchone()
        if not rec or (snapshot and rec["snapshot_id"] and rec["snapshot_id"]!=snapshot): raise ValueError("推荐与反馈对象不匹配")
    else:
        recommendation=context_for(db,kind,entity,snapshot)
        rec=db.execute("SELECT * FROM recommendation_contexts WHERE id=?",(recommendation,)).fetchone() if recommendation else None
    snapshot=snapshot or (rec["snapshot_id"] if rec else None)
    if action:
        a=db.execute("SELECT a.snapshot_id,s.dir_id,s.body FROM actions a JOIN snapshots s ON s.id=a.snapshot_id WHERE a.id=?",(action,)).fetchone()
        if not a or (snapshot and a["snapshot_id"]!=snapshot) or (kind=="direction" and a["dir_id"]!=entity) or (kind=="work" and entity not in json.loads(a["body"]).get("work_ids",[])):
            raise ValueError("行动与反馈对象不匹配")
        snapshot=a["snapshot_id"]
    if snapshot:
        s=db.execute("SELECT dir_id,body FROM snapshots WHERE id=?",(snapshot,)).fetchone()
        if not s or (kind=="direction" and s["dir_id"]!=entity) or (kind=="work" and entity not in json.loads(s["body"]).get("work_ids",[])):
            raise ValueError("快照与反馈对象不匹配")
    db.execute("INSERT INTO feedback_contexts VALUES(?,?,?,?,?)",(fid,recommendation,snapshot,action,dump({"origin":rec["origin"] if rec else "direct"})))


def signals(db,cutoff=None,limit=12):
    result=rows(db,"""SELECT f.id,f.entity_type,f.entity_id,f.dimension,f.value,f.reason,f.created_at,
          c.snapshot_id,c.action_id,r.profile_id,r.evaluation_id,r.reason recommended_because,r.features FROM feedback f
          JOIN feedback_contexts c ON c.feedback_id=f.id LEFT JOIN recommendation_contexts r ON r.id=c.recommendation_id
          WHERE f.dimension IN ('reading_value','comparison','career_value') AND (? IS NULL OR f.created_at<=?)
          ORDER BY f.created_at DESC,f.rowid DESC LIMIT ?""",(cutoff,cutoff,limit))
    for row in result: row["features"]=json.loads(row["features"] or "{}")
    return result


def link_outcome(db,eid,aid):
    a=db.execute("SELECT s.id,s.dir_id,s.body FROM actions a JOIN snapshots s ON s.id=a.snapshot_id WHERE a.id=?",(aid,)).fetchone()
    if not a: return
    works=json.loads(a["body"]).get("work_ids",[])
    feedback_ids=[f["id"] for f in db.execute("""SELECT f.* FROM feedback f JOIN feedback_contexts fc ON fc.feedback_id=f.id
        WHERE fc.snapshot_id=? OR fc.action_id=? OR (f.entity_type='direction' AND f.entity_id=?)""",(a["id"],aid,a["dir_id"]))]
    db.execute("INSERT OR IGNORE INTO outcome_contexts VALUES(?,?,?,?)",(eid,a["id"],dump(works),dump(feedback_ids)))


def outcome_examples(db,since=""):
    return rows(db,"""SELECT ev.id,ev.decision,ev.reason,ev.actual,ev.at,a.id action_id,a.title,c.snapshot_id,
           c.work_ids,c.feedback_ids FROM action_events ev JOIN actions a ON a.id=ev.action_id
           JOIN outcome_contexts c ON c.event_id=ev.id WHERE ev.at>? ORDER BY ev.at DESC LIMIT 25""",(since,))


def compare(db,evaluation_id):
    e=db.execute("SELECT * FROM evaluations WHERE id=?",(evaluation_id,)).fetchone()
    if not e: raise ValueError("比较集合不存在")
    groups={k:set(json.loads(e[k])) for k in ("baseline","selected")}
    # Each reader labels a work once for this comparison. Prefer the latest explicit judgement.
    labels={}
    for f in db.execute("""SELECT f.entity_id,f.value FROM feedback f JOIN feedback_contexts c ON f.id=c.feedback_id
          JOIN recommendation_contexts r ON c.recommendation_id=r.id WHERE r.evaluation_id=? AND f.dimension='reading_value'
          ORDER BY f.created_at,f.rowid""",(evaluation_id,)):
        labels[f[0]]=f[1]
    return {k:{"candidates":len(ids),"rated":len(ids&labels.keys()),"useful":sum(labels.get(i)=="useful" for i in ids)}
            for k,ids in groups.items()}

def baseline_contexts(db,run_id):
    e=db.execute("SELECT e.*,r.profile_id,r.created_at FROM evaluations e JOIN runs r ON r.id=e.run_id WHERE e.run_id=?",(run_id,)).fetchone()
    if not e:return
    included=set(json.loads(e["selected"]))
    for wid in json.loads(e["baseline"]):
        if wid in included:continue
        w=db.execute("SELECT title,metadata FROM works WHERE id=?",(wid,)).fetchone()
        if w: record(db,"work",wid,"同一候选集按主题相关性和日期排序",paper_features({**json.loads(w["metadata"]),"title":w["title"]}),
                     pid=e["profile_id"],evaluation=e["id"],origin="baseline",at=e["created_at"])
