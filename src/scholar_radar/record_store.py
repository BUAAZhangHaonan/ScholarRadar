"""Paper-specific analyses with independently checkable scope and source links."""
import json
import re
from pathlib import Path

from .db import key, rows
from .settings import dump, now

SECTION_NAMES = {
    "研究问题": "problem", "关键机制": "mechanism", "最近邻与比较": "comparison",
    "关键实验": "experiment", "适用条件": "conditions", "可复用部分": "reuse",
    "待补问题": "open_question", "研究变化": "finding",
}


def sections(answer):
    """Recognize explicitly named sections; keep older free prose intact."""
    names = "|".join(SECTION_NAMES)
    headings = list(re.finditer(
        rf"(?m)^\s*(?:#{{1,6}}\s*|[-*]\s+|\d+[.、)]\s*)?\**({names})\**\s*[：:]\**\s*",
        answer,
    ))
    return {SECTION_NAMES[h[1]]: answer[h.end():headings[i+1].start() if i+1<len(headings) else len(answer)].strip()
            for i,h in enumerate(headings)}


def evidence_ids(db, claim_id):
    return [r[0] for r in db.execute(
        "SELECT e.id FROM claim_evidence ce JOIN evidence e ON e.id=ce.evidence_id "
        "WHERE ce.claim_id=? ORDER BY e.start,e.end,e.id",(claim_id,))]


def save_record(db, *, wid, rid, cid, call_id, analysis_id, run_id, question, focus,
                heading, start, end, topic, direction_ids=()):
    claim=db.execute("""SELECT c.statement,c.conditions,v.total_chars FROM claims c
       JOIN revisions v ON v.id=? JOIN documents d ON d.id=v.document_id
       WHERE c.id=? AND c.kind='system_inference' AND d.kind='paper' AND d.work_id=?""",(rid,cid,wid)).fetchone()
    if not claim or json.loads(claim["conditions"]).get("revision")!=rid or not 0<=start<end<=claim["total_chars"]:
        raise ValueError("论文分析与固定版本或覆盖区间不一致")
    quotes=rows(db,"SELECT e.* FROM claim_evidence c JOIN evidence e ON c.evidence_id=e.id WHERE c.claim_id=?",(cid,))
    if not quotes or any(q["revision_id"]!=rid or q["start"]<start or q["end"]>end for q in quotes):
        raise ValueError("论文分析包含所读范围之外的引文")
    created=db.execute("""INSERT OR IGNORE INTO reading_records
       (id,work_id,revision_id,call_id,analysis_id,question,focus,heading,start,end,recorded_at,sections,topic)
       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(cid,wid,rid,call_id,analysis_id,question,focus or "overview",
                 heading,start,end,now(),dump(sections(claim["statement"])),topic or "")).rowcount
    if run_id:
        db.execute("INSERT OR IGNORE INTO reading_record_runs VALUES(?,?)",(cid,run_id))
    for did in direction_ids:
        db.execute("""INSERT OR IGNORE INTO reading_record_directions
             SELECT ?,id,'screen_selection' FROM directions WHERE id=? AND status!='merged'""",(cid,did))
    db.execute("""INSERT OR IGNORE INTO reading_record_directions SELECT ?,direction_id,'existing_membership'
               FROM memberships WHERE work_id=?""",(cid,wid))
    return bool(created)


def work_records(db,wid,revision_id=None,cutoff=None):
    records=rows(db,"""SELECT r.id,r.work_id,r.revision_id,r.id claim_id,r.analysis_id,
       r.question,r.focus,r.heading,r.recorded_at,r.sections,r.topic,r.start,r.end,
       v.total_chars,v.version,c.statement answer FROM reading_records r JOIN revisions v ON v.id=r.revision_id
       JOIN claims c ON c.id=r.id WHERE r.work_id=? AND (? IS NULL OR r.revision_id=?)
       AND (? IS NULL OR r.recorded_at<=?) ORDER BY
       CAST(substr(coalesce(v.version,'v0'),2) AS INTEGER) DESC,v.observed_at DESC,r.recorded_at DESC,r.rowid DESC""",
       (wid,revision_id,revision_id,cutoff,cutoff))
    for r in records:
        r["sections"]=json.loads(r["sections"])
        r["coverage"]={k:r.pop(k) for k in ("start","end","total_chars")}
        r["evidence_ids"]=evidence_ids(db,r["id"])
    return records


def research_updates(db,run_id,limit=5):
    out=[]
    seen=set()
    for row in db.execute("""SELECT r.id,r.work_id,r.sections,v.version,c.statement,w.title
        FROM reading_record_runs rr JOIN reading_records r ON r.id=rr.record_id JOIN revisions v ON v.id=r.revision_id
        JOIN claims c ON c.id=r.id JOIN works w ON w.id=r.work_id
        WHERE rr.run_id=? AND NOT EXISTS(SELECT 1 FROM reading_record_runs other JOIN runs before ON before.id=other.run_id
        JOIN runs current ON current.id=rr.run_id WHERE other.record_id=rr.record_id AND before.created_at<current.created_at)
        ORDER BY r.recorded_at DESC,r.rowid DESC""",(run_id,)):
        if row["work_id"] in seen: continue
        fields=json.loads(row["sections"]); body=fields.get("finding") or fields.get("experiment") or row["statement"]
        out.append({"work_id":row["work_id"],"record_id":row["id"],"title":row["title"],"body":body,
                    "evidence_ids":evidence_ids(db,row["id"]),"version":row["version"]})
        seen.add(row["work_id"])
        if len(out)>=limit: break
    return out


def backfill(db):
    """Enrich migrated records only after matching the successful upstream payload."""
    pending=rows(db,"""SELECT r.*,v.upstream_revision,c.statement FROM reading_records r
        JOIN revisions v ON v.id=r.revision_id JOIN claims c ON c.id=r.id WHERE r.call_id IS NULL""")
    indexed={}
    for r in pending:
        indexed.setdefault((r["upstream_revision"],r["question"],r["start"],r["end"],r["statement"]),[]).append(r)
    if not pending: return 0
    matches={}
    for call in db.execute("""SELECT id,remote_id,file FROM calls WHERE service='analysis' AND tool='analyze_paper'
                              AND status='done' AND file IS NOT NULL"""):
        try: data=json.loads(Path(call["file"]).read_text())
        except (OSError,ValueError): continue
        analysis=data.get("analysis") or {}; cov=analysis.get("coverage") or {}
        identity=(data.get("document_revision"),analysis.get("question"),cov.get("start"),cov.get("end"),analysis.get("answer"))
        for r in indexed.get(identity,[]):
            linked=set(evidence_ids(db,r["id"]))
            upstream=set()
            for piece in analysis.get("evidence",[]):
                loc=next(iter(piece.get("locations") or []),None)
                if loc: upstream.add(key("evidence",r["revision_id"],loc["start"],loc["end"]))
            if linked==upstream and data.get("analysis_id")==call["remote_id"] and call["remote_id"]:
                matches.setdefault(r["id"],[]).append((call["id"],call["remote_id"]))
    count=0
    for r in pending:
        options=matches.get(r["id"],[])
        if len(options)!=1: continue
        call_id,remote=options[0]
        db.execute("UPDATE reading_records SET call_id=?,analysis_id=?,sections=? WHERE id=?",
                   (call_id,remote,dump(sections(r["statement"])),r["id"]))
        count+=1
    return count
