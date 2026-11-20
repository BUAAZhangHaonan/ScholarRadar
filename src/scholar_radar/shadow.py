import json
from datetime import date,timedelta

from .db import rows,key
from .factors import propose
from .settings import dump,now

RULES={"has_located_evidence","linked_resource","independent_support"}


def refresh(db,run_id=None):
    if not db.execute("SELECT 1 FROM proposals LIMIT 1").fetchone():
        propose(db,{"target":"阅读后能否明确说出研究判断的变化","input":"固定候选中的作品是否拥有可回查原文",
             "method":"has_located_evidence","window_days":28,"missing":"保留未知","overlap":"与证据进展因子比较",
             "comparison":"同一候选、同一截止时间，盲评与时间相关性基准分歧的作品"})
    sets=rows(db,"SELECT * FROM evaluations WHERE (? IS NULL OR run_id=?)",(run_id,run_id))
    for p in db.execute("SELECT * FROM proposals WHERE lifecycle IN ('shadow','active')"):
        f=json.loads(p["definition"]); rule=f.get("method")
        if rule not in RULES: continue
        for evaluation in sets:
            if db.execute("SELECT 1 FROM shadow_choices WHERE proposal_id=? AND evaluation_id=?",(p["id"],evaluation["id"])).fetchone(): continue
            candidates=json.loads(evaluation["candidates"]); baseline=json.loads(evaluation["baseline"])
            cutoff=db.execute("SELECT max(generated_at) FROM reports WHERE run_id=?",(evaluation["run_id"],)).fetchone()[0] or now()
            score={}
            for wid in candidates:
                if rule=="has_located_evidence":
                    value=db.execute("""SELECT EXISTS(SELECT 1 FROM evidence e JOIN revisions v ON e.revision_id=v.id
                       JOIN documents d ON d.id=v.document_id WHERE d.work_id=? AND v.observed_at<=?)""",(wid,cutoff)).fetchone()[0]
                elif rule=="linked_resource":
                    value=db.execute("""SELECT EXISTS(SELECT 1 FROM work_resources wr WHERE wr.work_id=? AND EXISTS(
                        SELECT 1 FROM documents d JOIN revisions v ON v.document_id=d.id WHERE d.work_id=wr.work_id AND v.observed_at<=?))""",(wid,cutoff)).fetchone()[0]
                else:
                    value=db.execute("""SELECT count(DISTINCT m2.work_id) FROM memberships m JOIN memberships m2
                       ON m.direction_id=m2.direction_id WHERE m.work_id=? AND m2.work_id!=m.work_id AND m.created_at<=? AND m2.created_at<=?""",(wid,cutoff,cutoff)).fetchone()[0]
                score[wid]=value
            positions={wid:i for i,wid in enumerate(baseline)}
            ranked=sorted(candidates,key=lambda w:(-score[w],positions.get(w,len(candidates)),w))
            due=date.fromisoformat(evaluation["as_of"])+timedelta(days=int(f["window_days"]))
            db.execute("INSERT INTO shadow_choices VALUES(?,?,?,?,?,?)",
                       (p["id"],evaluation["id"],dump(ranked[:len(baseline)]),now(),"pending",str(due)))


def disagreements(db,evaluation):
    alt=set(json.loads(evaluation["selected"]))
    for row in db.execute("SELECT order_json FROM shadow_choices WHERE evaluation_id=?",(evaluation["id"],)):
        alt.update(json.loads(row[0]))
    return set(json.loads(evaluation["baseline"]))^alt
