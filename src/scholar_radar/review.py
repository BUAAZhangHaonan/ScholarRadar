import json
from .db import database,rows
from .models import ask
from .profile import get_profile
from .settings import dump,now


async def review(run):
    with database() as db:
        cards=rows(db,"""SELECT s.* FROM snapshots s LEFT JOIN assessment_reviews r ON r.snapshot_id=s.id
                   WHERE s.run_id=? AND r.snapshot_id IS NULL ORDER BY s.id""",(run["id"],))
        profile=get_profile(db,run["profile_id"])
        materials=[]
        for i,s in enumerate(cards,1):
            b=json.loads(s["body"])
            quotes=rows(db,"""SELECT e.id,e.quote,e.start,e.end,v.body,d.kind,w.title FROM snapshot_evidence se JOIN evidence e ON se.evidence_id=e.id
                 JOIN revisions v ON v.id=e.revision_id JOIN documents d ON d.id=v.document_id LEFT JOIN works w ON w.id=d.work_id
                 WHERE se.snapshot_id=? ORDER BY e.id""",(s["id"],))
            evidence=[{"id":q["id"],"source":q["title"] or q["kind"],"quote":q["quote"],
                       "context":q["body"][max(0,q["start"]-230):q["end"]+230]} for q in quotes]
            materials.append({"id":"C"+str(i),"judgment":b["judgment"],"change":b["change"],"history":b["history"],
                              "nearest":b["nearest"],"hypothesis":b["forecast"],"job":b.get("job_match"),"evidence":evidence})
    if not materials: return {"reviewed":0}
    data=await ask("entailment_review",profile["strong_model"],
      "逐卡独立复核。核对事实是否有给定原文依据、数据集与指标是否一致、岗位是否来自官方要求。"
      "假设和未来判定条件应与已发生事实区分。仅因未来结果未知不能否定一个有根据的可证伪假设。"
      "返回 {reviews:[{id,verdict,reason}]}，id=C1等。verdict取 supported 或 needs_evidence。"
      "对有实质性错误的卡注明哪句话及缺少什么，不能用宽泛免责代替核对。",materials,run["id"],max_tokens=2000)
    seq={r.get("id"):r for r in data.get("reviews",[])}
    with database(write=True) as db:
        for card,item in zip(cards,materials):
            v=seq.get(item["id"],{})
            verdict=v.get("verdict") if v.get("verdict") in {"supported","needs_evidence"} else "needs_evidence"
            db.execute("INSERT OR IGNORE INTO assessment_reviews VALUES(?,?,?,?,?,?)",
                       (card["id"],now(),verdict,v.get("reason") or "复核输出缺少此方向",
                        dump([e["id"] for e in item["evidence"]]),profile["strong_model"]))
    return {"reviewed":len(cards),"supported":sum(v.get("verdict")=="supported" for v in seq.values())}
