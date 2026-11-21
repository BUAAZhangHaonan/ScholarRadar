import json
from .db import database, key, rows
from .models import ask
from .profile import get_profile
from .settings import dump, now


async def review(run):
    with database() as db:
        cards = rows(
            db,
            """SELECT s.* FROM snapshots s LEFT JOIN assessment_reviews r ON r.snapshot_id=s.id
                   WHERE s.run_id=? AND r.snapshot_id IS NULL ORDER BY s.id""",
            (run["id"],),
        )
        profile = get_profile(db, run["profile_id"])
        materials = []
        for i, s in enumerate(cards, 1):
            b = json.loads(s["body"])
            quotes = rows(
                db,
                """SELECT e.id,e.quote,e.start,e.end,e.revision_id,v.body,d.kind,d.work_id,w.title FROM snapshot_evidence se JOIN evidence e ON se.evidence_id=e.id
                 JOIN revisions v ON v.id=e.revision_id JOIN documents d ON d.id=v.document_id LEFT JOIN works w ON w.id=d.work_id
                 WHERE se.snapshot_id=? ORDER BY e.id""",
                (s["id"],),
            )
            evidence = [
                {
                    "id": q["id"],
                    "source": q["title"] or q["kind"],
                    "work_id": q["work_id"],
                    "revision_id": q["revision_id"],
                    "quote": q["quote"],
                    "context": q["body"][max(0, q["start"] - 230) : q["end"] + 230],
                }
                for q in quotes
            ]
            materials.append(
                {
                    "id": "C" + str(i),
                    "judgment": b["judgment"],
                    "change": b["change"],
                    "history": b["history"],
                    "nearest": b["nearest"],
                    "hypothesis": b["forecast"],
                    "job": b.get("job_match"),
                    "resources": b.get("resources"),
                    "personal_feasibility": b.get("feasibility"),
                    "action": b.get("action"),
                    "user_compute_conditions": profile["compute"],
                    "evidence": evidence,
                }
            )
    if not materials:
        return {"reviewed": 0}
    data = await ask(
        "entailment_review",
        profile["strong_model"],
        "逐卡独立复核。核对事实是否有给定原文依据、数据集与指标是否一致、岗位是否来自官方要求。研究资源的可安排程度以画像明确记录为准，条件性资源的方案保留前提。"
        "假设和未来判定条件应与已发生事实区分。仅因未来结果未知不能否定一个有根据的可证伪假设。"
        "每项返回 {id,verdict,reason,gap}，id=C1等。verdict取 supported 或 needs_evidence。"
        "已支持填 gap=null。需要修改时 gap={kind,question,anchor,neighbor}；"
        "仅措辞有误时 kind=wording，缺实验证据填 experiment，缺方法填 method，缺限制填 conditions，缺最近邻比较填 neighbor。"
        "question 写一个具体、可由材料回答的问题；anchor 逐字选一条来自目标论文的证据ID。"
        "neighbor 填需核查的真实论文题目/外部标识，尚无明确作品填空；确实无法补证填 unresolved。"
        "不要为一个清楚标明的未来验证要求预先提供其预期结果。必要条件未证实应作为开放问题保留。"
        "对有实质性错误的卡注明哪句话及缺少什么，不能用宽泛免责代替核对。",
        materials,
        run["id"],
        max_tokens=2000,
    )
    entries=data.get("reviews",data.get("cards"))
    if not isinstance(entries,list):
        raise ValueError("复核返回缺少结构化结果列表")
    seq={r["id"]:r for r in entries if isinstance(r,dict) and r.get("id")}
    expected={item["id"] for item in materials}
    if set(seq)!=expected or len(entries)!=len(expected) or any(
            r.get("verdict") not in {"supported","needs_evidence"} or not r.get("reason") for r in seq.values()):
        raise ValueError("复核返回缺少已提交方向的明确结论")
    with database(write=True) as db:
        for card, item in zip(cards, materials):
            v = seq.get(item["id"], {})
            verdict = (
                v.get("verdict")
                if v.get("verdict") in {"supported", "needs_evidence"}
                else "needs_evidence"
            )
            db.execute(
                "INSERT OR IGNORE INTO assessment_reviews VALUES(?,?,?,?,?,?)",
                (
                    card["id"],
                    now(),
                    verdict,
                    v.get("reason") or "复核输出缺少此方向",
                    dump([e["id"] for e in item["evidence"]]),
                    profile["strong_model"],
                ),
            )
            if verdict == "needs_evidence":
                gap = v.get("gap") if isinstance(v.get("gap"), dict) else {}
                kind = gap.get("kind")
                if kind not in {
                    "wording",
                    "experiment",
                    "method",
                    "conditions",
                    "neighbor",
                }:
                    kind = "unresolved"
                anchor = next(
                    (
                        e
                        for e in item["evidence"]
                        if e["id"] == gap.get("anchor") and e["work_id"]
                    ),
                    None,
                )
                question = str(gap.get("question") or v.get("reason") or "").strip()
                if kind not in {"wording", "unresolved"} and (
                    not anchor or not question
                ):
                    kind = "unresolved"
                wid = anchor["work_id"] if anchor else None
                rev = anchor["revision_id"] if anchor else None
                gid = key("review gap", card["id"], kind, question, wid, rev)
                db.execute(
                    "INSERT OR IGNORE INTO research_gaps VALUES(?,?,?,?,?,?,?,'open',NULL,?)",
                    (
                        gid,
                        card["id"],
                        card["dir_id"],
                        wid,
                        rev,
                        kind,
                        question,
                        dump(
                            {
                                "anchor": gap.get("anchor"),
                                "neighbor": gap.get("neighbor") or "",
                            }
                        ),
                    ),
                )
    return {
        "reviewed": len(cards),
        "supported": sum(v.get("verdict") == "supported" for v in seq.values()),
    }
