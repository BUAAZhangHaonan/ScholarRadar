from datetime import datetime,UTC
import json
from .db import rows


def replay(db,cutoff):
    t=datetime.fromisoformat(cutoff.replace("Z","+00:00"))
    if t.tzinfo is None: raise ValueError("回放时间需要带时区")
    end=t.astimezone(UTC).isoformat(timespec="seconds")
    entries=rows(db,"SELECT * FROM report_versions WHERE generated_at<=? ORDER BY generated_at,id",(end,))
    result=[]
    for row in entries:
        doc=json.loads(row["body"])
        evidence=doc.get("evidence",[])
        permitted=[]
        for e in evidence:
            fixed=db.execute("SELECT observed_at FROM revisions WHERE id=?",(e["revision_id"],)).fetchone()
            if fixed and fixed[0]<=end: permitted.append(e["id"])
        if len(permitted)!=len(evidence): continue
        rid=db.execute("SELECT run_id FROM reports WHERE id=?",(row["report_id"],)).fetchone()[0]
        model_rows=rows(db,"""SELECT DISTINCT c.tool,json_extract(c.args,'$.model') model FROM calls c JOIN run_calls r ON c.id=r.call_id
                              WHERE r.run_id=? AND c.service='model' AND c.started_at<=?""",(rid,end))
        result.append({"snapshot_id":row["id"],"profile_version":doc["profile_version"],"scope_version":doc["coverage"]["scope_version"],
             "generated_at":row["generated_at"],"as_of":doc["as_of"],"query_coverage":doc["coverage"],"factor_versions":rows(db,
             "SELECT DISTINCT f.factor_id,f.factor_version FROM factor_values f JOIN snapshots s ON s.id=f.snapshot_id WHERE s.run_id=?",(rid,)),
             "model_roles":model_rows,"evidence_ids":permitted,"directions":doc.get("directions",[])})
    return {"cutoff":end,"editions":result,"evaluation":"历史可得性与流程回放"}


def forward(db,today):
    items=rows(db,"""SELECT f.dimension,f.value,count(*) count FROM feedback f GROUP BY f.dimension,f.value""")
    actions=rows(db,"SELECT decision,reason,actual,at FROM action_events ORDER BY at DESC LIMIT 80")
    pending=rows(db,"SELECT id,as_of,status FROM evaluations ORDER BY as_of DESC LIMIT 80")
    shadow=rows(db,"SELECT proposal_id,evaluation_id,status,horizon_due FROM shadow_choices")
    for s in shadow:
        s["horizon_state"]="pending" if s["horizon_due"]>today else "due"
    return {"observed_through":today,"explicit_feedback":items,"action_results":actions,"fixed_sets":pending,"shadow":shadow}
