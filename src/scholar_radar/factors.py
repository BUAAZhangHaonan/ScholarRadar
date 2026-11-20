import json
from datetime import date,timedelta
from .db import key
from .settings import dump,now


def activity(db, direction, scope, end, version="1"):
    end=date.fromisoformat(str(end)[:10])
    windows=[(end-timedelta(days=56),end-timedelta(days=28)),(end-timedelta(days=28),end)]
    counts=[]
    for a,b in windows:
        covers=db.execute("""SELECT DISTINCT source FROM coverage WHERE flow='observation' AND query='submitted'
            AND scope=? AND start<=? AND end>=? AND complete=1 AND classified=1""",(scope,str(a),str(b))).fetchall()
        if len(covers)!=1: return None,"两个 28 天窗口需同源、完整采集并按同一规则归类"
        source=covers[0][0]
        if counts and counts[0]["source"]!=source: return None,"前后窗口的数据源不同"
        members=db.execute("""SELECT o.work_id,min(o.membership_version) rule FROM observed o WHERE scope=? AND source=?
             AND event_time>=? AND event_time<? GROUP BY o.work_id""",(scope,source,str(a),str(b))).fetchall()
        if not members or any(row["rule"]!=version for row in members): return None,"分母为空或仍有作品待统一回标"
        n=db.execute("""SELECT count(DISTINCT o.work_id) FROM observed o JOIN memberships m ON m.work_id=o.work_id
             WHERE o.scope=? AND o.source=? AND o.event_time>=? AND o.event_time<? AND m.direction_id=? AND m.rule_version=?""",
             (scope,source,str(a),str(b),direction,version)).fetchone()[0]
        counts.append({"source":source,"start":str(a),"end":str(b),"n":n,"N":len(members),"share":n/len(members)})
    return {"windows":counts,"delta_pp":100*(counts[1]["share"]-counts[0]["share"]),"team_count":None},None


def put_values(db,snapshot,card,valid_ids,stats):
    table={"activity_share_change":stats,"evidence_progress":(card["judgment"],None),
           "reproducibility":(card.get("resources"),None),"research_opening":(card.get("forecast"),None),
           "personal_feasibility":(card.get("feasibility"),None),"career_match":(card.get("job_match"),None)}
    for name,(value,why) in table.items():
        if name=="career_match" and not (isinstance(value,dict) and value.get("evidence_ids")):
            value=None
        if value in (None,{},[],""):
            value=None; why=why or "本次输入缺少相应的可定位证据"
        db.execute("INSERT OR IGNORE INTO factor_values VALUES(?,?,?,?,?,?)",
                   (snapshot,name,"1",dump(value) if value is not None else None,why,dump(valid_ids)))


def propose(db,definition):
    needed={"target","input","method","window_days","missing","overlap","comparison"}
    if not needed<=set(definition) or any(not definition[k] for k in needed): raise ValueError("候选因子定义不完整")
    pid=key("proposal",definition)
    db.execute("INSERT OR IGNORE INTO proposals VALUES(?,?,'proposed',?)",(pid,dump(definition),now()))
    return pid


def transition(db,pid,state):
    r=db.execute("SELECT lifecycle FROM proposals WHERE id=?",(pid,)).fetchone()
    steps={"proposed":{"reviewed","retired"},"reviewed":{"shadow","retired"},"shadow":{"active","retired"}}
    if not r or state not in steps.get(r[0],set()): raise ValueError("候选因子状态转换无效")
    db.execute("UPDATE proposals SET lifecycle=?,updated_at=? WHERE id=?",(state,now(),pid))
