import json
from datetime import date, timedelta

from .bibliography import external_key, recent_candidates, shortlist
from .db import database, key,rows
from .discovery import discover_papers
from .evidence import arxiv_id, work
from .profile import get_profile
from .candidate_pool import remember,eligible,mark
from .queue import job
from .readings import read_paper
from .settings import VAR, atomic_text, dump


def coverage(
    db,
    rid,
    source,
    flow,
    scope,
    query,
    start,
    end,
    count,
    unique,
    status,
    *,
    complete=False,
    classified=False,
    cursor=None,
    path=None,
    reason=None,
):
    db.execute(
        "INSERT OR REPLACE INTO coverage VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            key(rid, source, scope, query, str(start), str(end)),
            rid,
            source,
            flow,
            scope,
            query,
            str(start),
            str(end),
            cursor,
            count,
            unique,
            int(complete),
            int(classified),
            status,
            path,
            reason,
        ),
    )


def folder(rid):
    return VAR / "runs" / rid


def identifiers(p):
    aid = arxiv_id(
        p.get("arxiv_id")
        or str(p.get("doi", "")).lower().removeprefix("10.48550/arxiv.")
    )[0]
    return {
        "arxiv": aid,
        "doi": p.get("doi"),
        "s2": p.get("s2_id"),
        "scholartrace": p.get("paper_id"),
        "openalex": p.get("openalex_id"),
    }


async def collect(run):
    rid = run["id"]
    day = date.fromisoformat(run["as_of"])
    cold = json.loads(run["detail"])["cold"]
    start = day - timedelta(days=90 if cold else 3)
    gathered = []
    issues = []
    try:
        result = await discover_papers(day, cold, rid)
        papers = result.get("papers", [])
        gathered.extend(papers)
        with database(write=True) as db:
            record = db.execute(
                "SELECT c.file FROM calls c JOIN run_calls r ON c.id=r.call_id WHERE r.run_id=? AND c.tool='query'",
                (rid,),
            ).fetchone()
            coverage(
                db,
                rid,
                "ScholarTrace",
                "discovery",
                run["scope"],
                "核心与相邻问题",
                start,
                day,
                len(papers),
                len(papers),
                result.get("status", "unknown"),
                path=record[0] if record else None,
                reason="；".join(map(str, result.get("errors", [])))
                or "主题精排，不代表固定观察范围",
            )
    except Exception as exc:
        issues.append(("ScholarTrace", str(exc)[:220]))
    def register(db,p):
        try: ident=external_key(p)
        except (TypeError,AttributeError): return None
        if not ident: return None
        p["work_id"]=work(db,p["title"],identifiers(p),p)
        remember(db,p)
        return p["work_id"]
    with database(write=True) as db:
        first=[register(db,p) for p in gathered]
        backlog=eligible(db,run["profile_id"],run["scope"],20 if cold else 3,[v for v in first if v])
    if (cold and len(backlog)<20) or (not cold and len(backlog)<3):
        try:
            extra, batches = await recent_candidates(day, cold, rid)
            gathered.extend(extra)
            with database(write=True) as db:
                for b in batches:
                    record = db.execute(
                        "SELECT file FROM calls WHERE id=?", (b["call_id"],)
                    ).fetchone()
                    coverage(
                        db,
                        rid,
                        "Semantic Scholar",
                        "discovery",
                        "date-discovery-v1",
                        b["query"],
                        b["start"],
                        b["end"],
                        b["returned"],
                        None,
                        "partial" if b["truncated"] else "ok",
                        path=record[0],
                        reason="限定日期补充检索，仅参与证据判断",
                    )
        except Exception as exc:
            issues.append(("Semantic Scholar", str(exc)[:220]))
    items = {}
    for p in gathered:
        try:
            k = external_key(p)
        except (AttributeError, TypeError):
            continue
        if k:
            items.setdefault(k, p)
    with database(write=True) as db:
        for name, error in issues:
            coverage(
                db,
                rid,
                name,
                "discovery",
                run["scope"],
                "采集失败",
                start,
                day,
                None,
                None,
                "failed",
                reason=error,
            )
        for p in items.values():
            register(db,p)
    atomic_text(folder(rid) / "candidates.json", dump(list(items.values())))
    if not items and issues:
        raise ValueError(str(issues))
    return {"candidates": len(items), "issues": issues}


async def screen(run):
    rid = run["id"]
    items = json.loads((folder(rid) / "candidates.json").read_text())
    cold = json.loads(run["detail"])["cold"]
    limit=20 if cold else 3
    with database() as db: profile=get_profile(db,run["profile_id"])
    preferred=[p["work_id"] for p in items if p.get("work_id")]
    with database() as db:
        done=rows(db,"SELECT material FROM selection_material WHERE run_id=? ORDER BY rowid",(rid,))
        considered=rows(db,"SELECT ci.body,c.work_id FROM candidate_decisions c JOIN candidate_inventory ci ON ci.work_id=c.work_id WHERE c.run_id=? ORDER BY c.rowid",(rid,))
    selection=[json.loads(x["material"]) for x in done]
    candidates=[{**json.loads(x["body"]),"work_id":x["work_id"]} for x in considered]
    # Alternate new discoveries and the oldest untouched work. Each considered
    # abstract advances the inventory, including when the result is empty.
    for _ in range(max(0,(4 if cold else 2)-(len(candidates)+23)//24)):
        with database() as db:
            batch=eligible(db,profile["id"],run["scope"],24,preferred)
        if not batch or len(selection)>=limit: break
        choices=await shortlist(batch,profile,limit-len(selection),rid)
        with database(write=True) as db:
            mark(db,run,batch,choices)
            for p in choices:
                db.execute("INSERT OR IGNORE INTO selection_material VALUES(?,?,?)",(rid,p["work_id"],dump(p)))
        candidates.extend(batch); selection.extend(choices)
    with database(write=True) as db:
        for p in selection:
            wk = external_key(p)
            db.execute(
                "INSERT OR IGNORE INTO readings VALUES(?,?,?,'queued','{}')",
                (rid, wk, dump(p)),
            )
            job(db, rid, "read", {"key": wk})
        fixed = [p["work_id"] for p in candidates]
        base = [
            p["work_id"]
            for p in sorted(
                candidates, key=lambda x: x.get("published_date") or "", reverse=True
            )
            if any(
                t in p["title"].lower()
                for t in (
                    "hallucin",
                    "multimodal",
                    "agent",
                    "instruction",
                    "tool",
                    "selective",
                )
            )
        ][:limit]
        db.execute(
            "INSERT OR IGNORE INTO evaluations VALUES(?,?,?,?,?,?,'pending')",
            (
                key("baseline", rid),
                rid,
                dump(fixed),
                dump(base),
                dump([p["work_id"] for p in selection]),
                run["as_of"],
            ),
        )
        from .recommendations import record,paper_features
        for p in selection:
            record(db,"work",p["work_id"],p.get("selection_reason") or "",paper_features(p),
                   pid=run["profile_id"],evaluation=key("baseline",rid),origin="screen",used=p.get("feedback_ids",[]))
    return {"selected": len(selection), "candidate_count": len(candidates)}


async def reading(run, payload):
    rid = run["id"]
    wk = payload["key"]
    with database() as db:
        p = json.loads(
            db.execute(
                "SELECT paper FROM readings WHERE run_id=? AND work_key=?", (payload.get("origin_run_id",rid), wk)
            ).fetchone()[0]
        )
    if payload.get("focus"):
        return await read_paper({**p, "evidence_focus": payload["focus"],"target_revision_id":payload["revision_id"],"analysis_question":payload.get("question")}, rid)
    try:
        result = await read_paper(p, rid)
    except Exception as exc:
        with database(write=True) as db:
            db.execute(
                "UPDATE readings SET status='failed',outcome=? WHERE run_id=? AND work_key=?",
                (dump({"error": str(exc)[:300]}), rid, wk),
            )
        raise
    with database(write=True) as db:
        db.execute(
            "UPDATE readings SET status='done',outcome=? WHERE run_id=? AND work_key=?",
            (dump(result), rid, wk),
        )
    return result


async def complete_cold_batch(run):
    """Fill available first-batch slots when a configured core theme lacks an anchored reading."""
    if not json.loads(run["detail"])["cold"]:
        return {"additional": 0}
    rid = run["id"]
    with database() as db:
        existing = list(
            db.execute(
                "SELECT work_key,paper,status FROM readings WHERE run_id=?", (rid,)
            )
        )
        profile = get_profile(db, run["profile_id"])
    slots = min(4, 20 - len(existing))
    if slots < 1:
        return {"additional": 0}

    def core(p):
        title = p["title"].lower()
        return ("hallucinat" in title or "conflict" in title) and any(
            w in title
            for w in ("visual", "vision", "multimodal", "multi-modal", "image")
        )

    if (
        sum(core(json.loads(r["paper"])) for r in existing if r["status"] == "done")
        >= 2
    ):
        return {"additional": 0}
    known = {r["work_key"] for r in existing}
    candidates = [
        p
        for p in json.loads((folder(rid) / "candidates.json").read_text())
        if core(p) and p.get("arxiv_id") and external_key(p) not in known
    ]
    chosen = await shortlist(candidates, profile, slots, rid)
    with database(write=True) as db:
        for p in chosen:
            wk = external_key(p)
            db.execute(
                "INSERT OR IGNORE INTO readings VALUES(?,?,?,'queued','{}')",
                (rid, wk, dump(p)),
            )
            job(db, rid, "read", {"key": wk})
        selected = [
            json.loads(r[0])["work_id"]
            for r in db.execute(
                "SELECT paper FROM readings WHERE run_id=? ORDER BY rowid", (rid,)
            )
        ]
        db.execute(
            "UPDATE evaluations SET selected=? WHERE run_id=?", (dump(selected), rid)
        )
    return {"additional": len(chosen), "reason": "补足缺少固定原文的核心研究问题"}
