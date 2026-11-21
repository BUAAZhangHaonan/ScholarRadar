import json
from datetime import date, timedelta

from .db import database, key, rows
from .models import ask
from .evidence import versioned_url
from .profile import get_profile
from .settings import ROOT, atomic_text, dump, now


def cost_summary(db, rid=None):
    if rid:
        values = rows(
            db,
            """SELECT u.* FROM receipts u JOIN run_calls r ON r.call_id=u.call_id
                          WHERE r.run_id=? AND r.cached=0""",
            (rid,),
        )
        pending = db.execute(
            """SELECT count(*) FROM calls c JOIN run_calls r ON c.id=r.call_id
                           WHERE r.run_id=? AND c.status IN ('sent','unknown_outcome')""",
            (rid,),
        ).fetchone()[0]
    else:
        values = rows(db, "SELECT * FROM receipts")
        pending = db.execute(
            "SELECT count(*) FROM calls WHERE status IN ('sent','unknown_outcome')"
        ).fetchone()[0]
    unknown = (
        sum(x["upper_bound"] is None and x["amount"] is None for x in values) + pending
    )
    return {
        "currency": "CNY",
        "known_lower": round(
            sum(x["lower_bound"] or x["amount"] or 0 for x in values), 6
        ),
        "known_upper": None
        if unknown
        else round(
            sum(
                x["upper_bound"] if x["upper_bound"] is not None else x["amount"] or 0
                for x in values
            ),
            6,
        ),
        "unknown": unknown,
        "receipts": len(values),
        "historical": round(sum(x["historical"] or 0 for x in values), 6),
    }


def evidence_rows(db, ids):
    if not ids:
        return []
    sql = """SELECT e.id,e.quote,e.start,e.end,e.line_start,e.line_end,v.id revision_id,v.version,v.mode,
           d.url,d.kind,d.work_id,w.title FROM evidence e JOIN revisions v ON e.revision_id=v.id
           JOIN documents d ON v.document_id=d.id LEFT JOIN works w ON w.id=d.work_id WHERE e.id IN ("""
    evidence = rows(db, sql + ",".join("?" for i in ids) + ")", ids)
    for item in evidence:
        item["url"] = versioned_url(item["url"], item["version"])
    return evidence


def export(db, rid, selected):
    run = dict(db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone())
    ids = list(dict.fromkeys(e for s in selected for e in s["evidence_ids"]))
    marks = ",".join("?" for s in selected)
    actions = (
        rows(
            db,
            "SELECT * FROM actions WHERE snapshot_id IN (" + marks + ")",
            [s["id"] for s in selected],
        )
        if selected
        else []
    )
    for a in actions:
        a["action_id"] = a["id"]
        a["details"] = json.loads(a["details"])
    accepted = rows(
        db,
        "SELECT id AS action_id,snapshot_id,title,status FROM actions WHERE status IN ('accepted','active','completed')",
    )
    return {
        "schema_version": "1",
        "snapshot_id": key(rid, [s["id"] for s in selected]),
        "generated_at": now(),
        "as_of": max((s["as_of"] for s in selected), default=run["created_at"]),
        "profile_version": run["profile_id"],
        "coverage": {
            "scope_version": run["scope"],
            "window_start": run["as_of"],
            "window_end": run["as_of"],
            "sources": rows(
                db,
                "SELECT source,flow,query,start,end,status,complete,classified,returned,unique_count,reason FROM coverage WHERE run_id=?",
                (rid,),
            ),
        },
        "directions": selected,
        "evidence": evidence_rows(db, ids),
        "proposed_actions": actions,
        "accepted_actions": accepted,
    }


def markdown(report):
    labels = {"daily": "每日变化", "weekly": "每周研究判断", "monthly": "每月复盘"}
    text = [f"# {report['date']} · {labels[report['kind']]}", ""]
    if report.get("review"):
        text.extend([report["review"]["summary"], ""])
    for s in report["directions"]:
        card = s["card"]
        text.extend(
            ["## " + card["title"], "", card["judgment"], "", "**历史脉络**", ""]
        )
        for h in card["history"]:
            text.append(
                f"- {h['date'] or '首次观察 ' + h['first_observed'][:10]}　{h['event']}"
            )
        text.extend(
            [
                "",
                "**新增证据**　" + card["change"],
                "",
                "**待验证的预测**　" + card["forecast"]["hypothesis"],
                "",
                "支持条件　" + str(card["forecast"]["confirm"]),
                "",
                "反例条件　" + str(card["forecast"]["refute"]),
                "",
                "**下一步**　" + card["action"]["title"],
                "",
            ]
        )
    if not report["directions"]:
        text.extend(
            [
                "分析尚有未完成项，请结合来源覆盖查看。"
                if report.get("issues")
                else "当期没有通过证据校验的新方向变化。",
                "",
            ]
        )
    if report.get("watch"):
        text.extend(["## 保持观察", ""])
        for item in report["watch"]:
            text.append("- " + item["question"] + "　" + item["reason"])
        text.append("")
    for e in report["evidence"]:
        text.append(
            f"- [{e['title'] or '官方岗位'} · 第 {e['line_start']} 行]({e['url']})　`{e['id']}`"
        )
    text.extend(["", "## 来源与用量", ""])
    for src in report["coverage"]["sources"]:
        text.append(f"- {src['source']}　{src['status']}　{src['reason'] or ''}")
    c = report["cost"]
    text.append(f"- 已知费用下界 ¥{c['known_lower']:.6f}，待核算 {c['unknown']} 项。")
    return "\n".join(text) + "\n"


async def publish(run):
    rid = run["id"]
    kind = "daily" if run["kind"]=="research_update" else run["kind"]
    day = date.fromisoformat(run["as_of"])
    from .shadow import refresh

    if kind == "weekly":
        from .proposal_mining import mine

        await mine(run)

    with database(write=True) as state:
        refresh(state, rid if kind == "daily" else None)
    with database() as db:
        prof = get_profile(db, run["profile_id"])
        if kind == "daily":
            selected = rows(
                db,
                "SELECT s.* FROM snapshots s JOIN assessment_reviews a ON a.snapshot_id=s.id AND a.verdict='supported' WHERE s.run_id=? ORDER BY s.generated_at DESC,s.rowid DESC",
                (rid,),
            )
        else:
            end = day if kind == "weekly" else day.replace(day=1) - timedelta(days=1)
            start = end - timedelta(days=6) if kind == "weekly" else end.replace(day=1)
            selected = rows(
                db,
                """SELECT s.* FROM snapshots s JOIN assessment_reviews a ON a.snapshot_id=s.id AND a.verdict='supported'
                                JOIN runs r ON r.id=s.run_id WHERE r.as_of BETWEEN ? AND ?
                                ORDER BY s.generated_at DESC""",
                (str(start), str(end)),
            )
        from .period_history import evolution
        from .record_store import research_updates
        from .recommendations import signals
        series=evolution(db,start,end,prof["timezone"]) if kind!="daily" else []
        updates=research_updates(db,rid,limit=8) if kind=="daily" else []
        active={v[0] for v in db.execute("SELECT DISTINCT s.dir_id FROM actions a JOIN snapshots s ON s.id=a.snapshot_id WHERE a.status IN ('active','accepted')")}
        followed={f[0] for f in db.execute("""SELECT f.entity_id FROM feedback f WHERE f.dimension='follow' AND f.value='followed' AND f.rowid=(
              SELECT max(v.rowid) FROM feedback v WHERE v.entity_type='direction' AND v.entity_id=f.entity_id AND v.dimension='follow')""")}
        turning={v["direction_id"] for v in series if len({n["verdict"] for n in v["nodes"]})>1}
        selected.sort(key=lambda v:(v["dir_id"] in active,v["dir_id"] in followed,v["dir_id"] in turning),reverse=True)
        cards = []
        seen = set()
        for s in selected:
            if s["dir_id"] in seen:
                continue
            seen.add(s["dir_id"])
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT evidence_id FROM snapshot_evidence WHERE snapshot_id=?",
                    (s["id"],),
                )
            ]
            cards.append(
                {
                    "id": s["id"],
                    "direction_id": s["dir_id"],
                    "as_of": s["as_of"],
                    "card": json.loads(s["body"]),
                    "evidence_ids": ids,
                }
            )
            if (
                len(cards)
                >= prof["weekly_directions" if kind != "daily" else "daily_limit"]
            ):
                break
        obj = export(db, rid, cards)
        if kind != "daily":
            obj["coverage"]["sources"] = rows(
                db,
                """SELECT DISTINCT c.source,c.flow,c.status,c.reason FROM coverage c
                JOIN runs r ON r.id=c.run_id WHERE r.as_of BETWEEN ? AND ?""",
                (str(start), str(end)),
            )
            obj["coverage"]["window_start"] = str(start)
            obj["coverage"]["window_end"] = str(end)
        feedback=signals(db,limit=30) if kind!="daily" else []
        if kind!="daily":
            from datetime import datetime,time,UTC
            from zoneinfo import ZoneInfo
            begin=datetime.combine(start,time.min,ZoneInfo(prof["timezone"])).astimezone(UTC).isoformat()
            stop=datetime.combine(end+timedelta(days=1),time.min,ZoneInfo(prof["timezone"])).astimezone(UTC).isoformat()
            feedback=[f for f in feedback if begin<=f["created_at"]<stop]
            # Each selected question retains its opening position, all subsequent evidence and the user's outcomes.
            for v in series:
                if any(n.get("actions") or n.get("feedback") for n in v["nodes"]): v["has_user_outcome"]=True
    with database() as db:
        issues = rows(
            db,
            "SELECT stage,outcome FROM jobs WHERE run_id=? AND status='failed' ORDER BY stage,id",
            (rid,),
        )
    with database() as db:
        cutoff = run["as_of"] if kind == "daily" else str(end)
        low = run["as_of"] if kind == "daily" else str(start)
        pending = rows(
            db,
            """SELECT s.id,s.dir_id,d.question,a.reason FROM snapshots s JOIN runs r ON r.id=s.run_id
              JOIN directions d ON d.id=s.dir_id JOIN assessment_reviews a ON a.snapshot_id=s.id
              WHERE r.as_of BETWEEN ? AND ? AND a.verdict='needs_evidence' AND s.id=(SELECT s2.id FROM snapshots s2
              JOIN runs r2 ON r2.id=s2.run_id WHERE s2.dir_id=s.dir_id AND r2.as_of<=?
              ORDER BY s2.generated_at DESC,s2.rowid DESC LIMIT 1) ORDER BY d.id LIMIT 3""",
            (low, cutoff, cutoff),
        )
    report = {**obj, "kind": kind, "date": str(day), "issues": issues, "watch": pending}
    report.update(evolution=series,research_updates=updates)
    report["snapshot_id"] = key("research-edition-v2-reading-2",obj["snapshot_id"], issues, obj["coverage"], pending,series,updates,feedback)
    with database() as db:
        saved = db.execute(
            "SELECT body FROM report_versions WHERE id=?", (report["snapshot_id"],)
        ).fetchone()
    if saved:
        report = json.loads(saved[0])
        for action in report.get("proposed_actions", []):
            action["action_id"] = action["id"]
    if not saved and kind=="daily" and cards:
        from .reading_copy import editorial
        report["editorial"]=await editorial(run,prof,cards,obj["evidence"],updates)
    if not saved and kind != "daily" and (cards or series):
        review = await ask(
            kind + "_review",
            prof["strong_model"],
            "只使用给定方向快照和反馈，写中文复盘。返回 {summary,readings:[证据ID],proposal:{action_id,why},unresolved}。"
            "按期初判断、支持与反例、范围如何收窄、下一步来写，区分需补证和已复核的认识。读物最多五份，最多一个可选验证。"
            "没有实际反馈时保留待评价，不能预测录用、收益或岗位结果。",
            {
                "cards": cards,
                "actions": obj["proposed_actions"],
                "feedback": feedback,
                "period": kind,
                "evolution":series,
            },
            rid,
            max_tokens=2200,
        )
        allowed = {e["id"] for e in obj["evidence"]}
        works = {e["id"]: e["work_id"] for e in obj["evidence"] if e.get("work_id")}
        unique = {}
        for eid in review.get("readings", []):
            if eid in allowed and eid in works:
                unique.setdefault(works[eid], eid)
        review["readings"] = list(unique.values())[: prof["weekly_readings"]]
        if (review.get("proposal") or {}).get("action_id") not in {
            x["id"] for x in obj["proposed_actions"]
        }:
            review["proposal"] = None
        report["review"] = review
    with database(write=True) as db:
        if not saved:
            report["cost"] = cost_summary(db, rid)
        report_id = key(rid, kind)
        db.execute(
            """INSERT INTO reports VALUES(?,?,?,?,?,?) ON CONFLICT(run_id,kind) DO UPDATE SET
                      body=excluded.body,generated_at=excluded.generated_at""",
            (report_id, rid, kind, str(day), dump(report), report["generated_at"]),
        )
        db.execute(
            "INSERT OR IGNORE INTO report_versions VALUES(?,?,?,?)",
            (report["snapshot_id"], report_id, report["generated_at"], dump(report)),
        )
    out = ROOT / "exports" / str(day) / kind
    atomic_text(out / "report.md", markdown(report))
    atomic_text(
        out / "internprep.json", json.dumps(report, ensure_ascii=False, indent=2)
    )
    return {
        "report_id": key(rid, kind),
        "directions": len(report["directions"]),
        "evidence": len(report["evidence"]),
    }
