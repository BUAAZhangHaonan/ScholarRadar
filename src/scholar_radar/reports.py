import json
from datetime import date,datetime,timedelta,UTC
from zoneinfo import ZoneInfo

from .db import database,key,rows
from .models import ask
from .profile import get_profile
from .settings import ROOT,atomic_text,dump,now


def cost_summary(db,rid=None):
    if rid:
        values=rows(db,"""SELECT u.* FROM receipts u JOIN run_calls r ON r.call_id=u.call_id
                          WHERE r.run_id=? AND r.cached=0""",(rid,))
        pending=db.execute("""SELECT count(*) FROM calls c JOIN run_calls r ON c.id=r.call_id
                           WHERE r.run_id=? AND c.status IN ('sent','unknown_outcome')""",(rid,)).fetchone()[0]
    else:
        values=rows(db,"SELECT * FROM receipts")
        pending=db.execute("SELECT count(*) FROM calls WHERE status IN ('sent','unknown_outcome')").fetchone()[0]
    unknown=sum(x["upper_bound"] is None and x["amount"] is None for x in values)+pending
    return {"currency":"CNY","known_lower":round(sum(x["lower_bound"] or x["amount"] or 0 for x in values),6),
            "known_upper":None if unknown else round(sum(x["upper_bound"] if x["upper_bound"] is not None else x["amount"] or 0 for x in values),6),
            "unknown":unknown,"receipts":len(values),"historical":round(sum(x["historical"] or 0 for x in values),6)}


def evidence_rows(db,ids):
    if not ids: return []
    sql="""SELECT e.id,e.quote,e.start,e.end,e.line_start,e.line_end,v.id revision_id,v.version,v.mode,
           d.url,d.kind,d.work_id,w.title FROM evidence e JOIN revisions v ON e.revision_id=v.id
           JOIN documents d ON v.document_id=d.id LEFT JOIN works w ON w.id=d.work_id WHERE e.id IN ("""
    return rows(db,sql+",".join("?" for i in ids)+")",ids)


def export(db,rid,selected):
    run=dict(db.execute("SELECT * FROM runs WHERE id=?",(rid,)).fetchone())
    ids=list(dict.fromkeys(e for s in selected for e in s["evidence_ids"]))
    marks=",".join("?" for s in selected)
    actions=rows(db,"SELECT * FROM actions WHERE snapshot_id IN ("+marks+")",[s["id"] for s in selected]) if selected else []
    for a in actions: a["details"]=json.loads(a["details"])
    accepted=rows(db,"SELECT id AS action_id,snapshot_id,title,status FROM actions WHERE status IN ('accepted','active','completed')")
    return {"schema_version":"1","snapshot_id":key(rid,[s["id"] for s in selected]),"generated_at":now(),
            "as_of":max((s["as_of"] for s in selected),default=run["created_at"]),"profile_version":run["profile_id"],
            "coverage":{"scope_version":run["scope"],"window_start":run["as_of"],"window_end":run["as_of"],
                "sources":rows(db,"SELECT source,flow,query,start,end,status,complete,classified,returned,unique_count,reason FROM coverage WHERE run_id=?",(rid,))},
            "directions":selected,"evidence":evidence_rows(db,ids),"proposed_actions":actions,"accepted_actions":accepted}


def markdown(report):
    labels={"daily":"每日变化","weekly":"每周研究判断","monthly":"每月复盘"}
    text=[f"# {report['date']} · {labels[report['kind']]}",""]
    if report.get("review"): text.extend([report["review"]["summary"],""])
    for s in report["directions"]:
        card=s["card"]
        text.extend(["## "+card["title"],"",card["judgment"],"","**历史脉络**",""])
        for h in card["history"]: text.append(f"- {h['date'] or '首次观察 '+h['first_observed'][:10]}　{h['event']}")
        text.extend(["","**新增证据**　"+card["change"],"","**待验证的预测**　"+card["forecast"]["hypothesis"],"",
                     "支持条件　"+str(card["forecast"]["confirm"]),"","反例条件　"+str(card["forecast"]["refute"]),"",
                     "**下一步**　"+card["action"]["title"],""])
    if not report["directions"]: text.extend(["当期没有通过证据校验的新方向变化。",""])
    for e in report["evidence"]: text.append(f"- [{e['title'] or '官方岗位'} · 第 {e['line_start']} 行]({e['url']})　`{e['id']}`")
    text.extend(["","## 来源与用量",""])
    for src in report["coverage"]["sources"]: text.append(f"- {src['source']}　{src['status']}　{src['reason'] or ''}")
    c=report["cost"]
    text.append(f"- 已知费用下界 ¥{c['known_lower']:.6f}，待核算 {c['unknown']} 项。")
    return "\n".join(text)+"\n"


async def publish(run):
    rid=run["id"]; kind=run["kind"]; day=date.fromisoformat(run["as_of"])
    with database() as db:
        prof=get_profile(db,run["profile_id"])
        if kind=="daily":
            selected=rows(db,"SELECT * FROM snapshots WHERE run_id=? ORDER BY generated_at,rowid",(rid,))
        else:
            start=day-timedelta(days=6 if kind=="weekly" else 30)
            selected=rows(db,"""SELECT s.* FROM snapshots s JOIN runs r ON r.id=s.run_id WHERE r.as_of BETWEEN ? AND ?
                                ORDER BY s.generated_at DESC""",(str(start),str(day)))
        cards=[]; seen=set()
        for s in selected:
            if s["dir_id"] in seen: continue
            seen.add(s["dir_id"])
            ids=[r[0] for r in db.execute("SELECT evidence_id FROM snapshot_evidence WHERE snapshot_id=?",(s["id"],))]
            cards.append({"id":s["id"],"direction_id":s["dir_id"],"as_of":s["as_of"],"card":json.loads(s["body"]),"evidence_ids":ids})
            if len(cards)>=prof["weekly_directions" if kind!="daily" else "daily_limit"]: break
        obj=export(db,rid,cards)
        if kind!="daily":
            obj["coverage"]["sources"]=rows(db,"""SELECT DISTINCT c.source,c.flow,c.status,c.reason FROM coverage c
                JOIN runs r ON r.id=c.run_id WHERE r.as_of BETWEEN ? AND ?""",(str(start),str(day)))
            obj["coverage"]["window_start"]=str(start)
        actions=rows(db,"SELECT title,kind,status FROM actions ORDER BY created_at DESC LIMIT 20")
        feedback=rows(db,"SELECT dimension,value,count(*) count FROM feedback GROUP BY dimension,value")
    report={**obj,"kind":kind,"date":str(day)}
    if kind!="daily" and cards:
        review=await ask(kind+"_review",prof["strong_model"],
            "只使用给定方向快照和反馈，写中文复盘。返回 {summary,readings:[证据ID],proposal:{action_id,why},unresolved}。"
            "总结研究线索怎样演变、尚待验证的预测和判断条件。读物最多五份，最多一个可选验证。"
            "没有实际反馈时保留待评价，不能预测录用、收益或岗位结果。",
            {"cards":cards,"actions":obj["proposed_actions"],"feedback":feedback,"period":kind},rid,max_tokens=2200)
        allowed={e["id"] for e in obj["evidence"]}
        review["readings"]=[i for i in review.get("readings",[]) if i in allowed][:prof["weekly_readings"]]
        if (review.get("proposal") or {}).get("action_id") not in {x["id"] for x in obj["proposed_actions"]}: review["proposal"]=None
        report["review"]=review
    with database(write=True) as db:
        report["cost"]=cost_summary(db,rid)
        db.execute("INSERT OR IGNORE INTO reports VALUES(?,?,?,?,?,?)",(key(rid,kind),rid,kind,str(day),dump(report),now()))
        # Subsequent calls render the immutable report that was actually published.
        report=json.loads(db.execute("SELECT body FROM reports WHERE run_id=? AND kind=?",(rid,kind)).fetchone()[0])
    out=ROOT/"exports"/str(day)/kind
    atomic_text(out/"report.md",markdown(report))
    atomic_text(out/"internprep.json",json.dumps(report,ensure_ascii=False,indent=2))
    return {"report_id":key(rid,kind),"directions":len(report["directions"]),"evidence":len(report["evidence"])}
