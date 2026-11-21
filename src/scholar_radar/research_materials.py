"""Select research records by topic, real version and analysis, independent of publication."""

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .db import key, rows
from .record_store import work_records
from .settings import now

STOP = set(
    "with from this that their these those paper study results analysis large language models model using for are and the into approach based learning through can use".split()
)


def cutoff_for(run):
    if run.get("evidence_cutoff"):
        return run["evidence_cutoff"]
    end = datetime.combine(
        date.fromisoformat(run["as_of"][:10]) + timedelta(days=1),
        time.min,
        ZoneInfo("Asia/Shanghai"),
    )
    return min(now(), end.astimezone(UTC).isoformat(timespec="seconds"))


def terms(text):
    latin = {
        w for w in re.findall(r"[a-z][a-z0-9-]{2,}", text.lower()) if w not in STOP
    }
    han = set()
    for segment in re.findall(r"[\u3400-\u9fff]{3,}", text):
        for i in range(len(segment) - 2):
            han.add(segment[i : i + 3])
    return latin, han


def history_matches(db, query, cutoff, limit=8):
    latin, han = terms(query)
    found = {}
    if latin:
        # Frequency from this evidence corpus prioritizes specific research terms.
        words = [
            r[0]
            for r in db.execute(
                "SELECT term FROM reading_term_frequencies WHERE term IN ("
                + ",".join("?" for _ in latin)
                + ") ORDER BY doc,cnt,term LIMIT 30",
                tuple(latin),
            )
        ]
        if words:
            q = " OR ".join('"' + w + '"' for w in words)
            matched = db.execute(
                """SELECT f.work_id,bm25(reading_search,0,0,3,3,1,1) score FROM reading_search f
                   JOIN reading_records r ON r.id=f.record_id WHERE reading_search MATCH ? AND r.recorded_at<=?
                   ORDER BY score LIMIT ?""",
                (q, cutoff, limit * 5),
            )
            for pos, (wid, _) in enumerate(matched):
                found[wid] = max(found.get(wid, 0), 1 / (1 + pos))
    if han:
        # Prefer phrases recurring across more than one character window.
        keys = sorted(han)
        for batch_start in range(0, len(keys), 100):
            q = " OR ".join(
                '"' + w + '"' for w in keys[batch_start : batch_start + 100]
            )
            matches = db.execute(
                """SELECT r.work_id,f.topic,f.analysis FROM reading_phrases f JOIN reading_records r
                         ON r.id=f.record_id WHERE reading_phrases MATCH ? AND r.recorded_at<=?
                         ORDER BY bm25(reading_phrases,0,3,1) LIMIT ?""",
                (q, cutoff, limit * 5),
            )
            for row in matches:
                shared = han & terms(row[1] + " " + row[2])[1]
                found[row[0]] = max(found.get(row[0], 0), len(shared) / len(han))
    return [
        wid
        for wid, _ in sorted(found.items(), key=lambda pair: (-pair[1], pair[0]))[
            :limit
        ]
    ]


def linked_works(db, direction_id, cutoff):
    return [
        r[0]
        for r in db.execute(
            """SELECT work_id FROM (
       SELECT r.work_id,max(r.recorded_at) stamp FROM reading_record_directions a JOIN reading_records r ON r.id=a.record_id
         WHERE a.direction_id=? AND r.recorded_at<=? GROUP BY r.work_id
       UNION ALL SELECT m.work_id,max(m.created_at) stamp FROM memberships m
         WHERE m.direction_id=? AND m.created_at<=? GROUP BY m.work_id)
       GROUP BY work_id ORDER BY max(stamp) DESC,work_id""",
            (direction_id, cutoff, direction_id, cutoff),
        )
    ]


def paper_material(db, wid, cutoff, priority_record_ids=()):
    records = work_records(db, wid, cutoff=cutoff)
    if not records:
        return None
    # Version numbers are comparable within a document lineage. A publisher's
    # unnumbered revision and an arXiv v2 do not define a relative version.
    preferred = [r for r in records if r["id"] in priority_record_ids]
    chosen_source = max(
        preferred or records,
        key=lambda r: (r["revision_observed_at"], r["recorded_at"], r["id"]),
    )["document_id"]
    records = [r for r in records if r["document_id"] == chosen_source]
    rev = records[0]["revision_id"]
    active = [r for r in records if r["revision_id"] == rev]
    work = db.execute("SELECT * FROM works WHERE id=?", (wid,)).fetchone()
    meta = json.loads(work["metadata"])
    classified = {
        r[0]
        for r in db.execute(
            """SELECT rd.direction_id FROM reading_records r
           JOIN reading_record_directions rd ON rd.record_id=r.id WHERE r.work_id=? AND r.revision_id=?""",
            (wid, rev),
        )
    }
    paper = {
        "work_id": wid,
        "title": work["title"],
        "version": active[0]["version"],
        "revision_id": rev,
        "source_url": active[0]["source_url"],
        "date": meta.get("published_date"),
        "year": meta.get("year"),
        "first_seen": work["first_seen"],
        "direction_ids": sorted(classified),
        "reading_records": active,
        "quotes": {},
        "quote_roles": {},
    }
    for r in active:
        for ev in db.execute(
            """SELECT e.id,e.quote,e.stance FROM claim_evidence ce JOIN evidence e ON e.id=ce.evidence_id
                       WHERE ce.claim_id=? AND e.revision_id=? ORDER BY e.start,e.end""",
            (r["id"], rev),
        ):
            paper["quotes"][ev["id"]] = ev["quote"]
            paper["quote_roles"][ev["id"]] = ev["stance"]
    previous_records = [r for r in records if r["revision_id"] != rev]
    pinned = set(priority_record_ids)
    older = [r for r in previous_records if r["id"] in pinned]
    if previous_records and pinned.intersection(r["id"] for r in active):
        prior_revision = previous_records[0]["revision_id"]
        older.extend(
            r
            for r in previous_records
            if r["revision_id"] == prior_revision and r not in older
        )
    if older:
        comparisons = []
        for r in older:
            original = db.execute(
                "SELECT body FROM revisions WHERE id=?", (r["revision_id"],)
            ).fetchone()[0]
            evidence = {
                row["id"]: row["quote"]
                for row in db.execute(
                    "SELECT e.id,e.quote FROM evidence e JOIN claim_evidence ce ON ce.evidence_id=e.id WHERE ce.claim_id=? AND e.revision_id=?",
                    (r["id"], r["revision_id"]),
                )
            }
            comparisons.append(
                {
                    "record_id": r["id"],
                    "version": r["version"],
                    "revision_id": r["revision_id"],
                    "question": r["question"],
                    "answer": r["answer"],
                    "quotes": evidence,
                    "current_quotes_absent_verbatim_from_old_parse": [
                        eid for eid, q in paper["quotes"].items() if q not in original
                    ],
                    "role": "明确的旧修订参照；措辞差异需要结合实验条件判断。",
                }
            )
        paper["historical_comparison"] = comparisons
    paper["resources"] = rows(
        db,
        """SELECT res.id,res.url,o.status,o.observed_at,o.revision_id,o.details,e.quote
           FROM work_resources wr JOIN resources res ON res.id=wr.resource_id JOIN resource_observations o ON o.resource_id=res.id
           LEFT JOIN evidence e ON e.id=o.evidence_id WHERE wr.work_id=? AND o.observed_at<=? AND o.id=(
             SELECT o2.id FROM resource_observations o2 WHERE o2.resource_id=res.id AND o2.observed_at<=?
             ORDER BY o2.observed_at DESC,o2.rowid DESC LIMIT 1) ORDER BY res.id""",
        (wid, cutoff, cutoff),
    )
    for r in paper["resources"]:
        r["details"] = json.loads(r["details"])
    paper["artifacts"] = rows(
        db,
        """SELECT a.id,a.kind,a.path,a.version,a.url,a.source_url,a.evidence_id,e.quote
        FROM work_resources wr JOIN verified_artifacts a ON a.resource_id=wr.resource_id JOIN evidence e ON e.id=a.evidence_id
        WHERE wr.work_id=? AND a.first_verified_at<=? ORDER BY a.kind,a.path,a.version""",
        (wid, cutoff),
    )
    return paper


def select_papers(db, run, direction=None, changes=(), extra_works=()):
    cutoff = cutoff_for(run)
    mandatory = list(extra_works)
    incoming = [c["entity_id"] for c in changes if c["kind"] == "reading"]
    mandatory.extend(incoming)
    if direction:
        linked = linked_works(db, direction["id"], cutoff)
        for c in changes:
            if c["kind"] == "resource":
                mandatory.extend(
                    r[0]
                    for r in db.execute(
                        "SELECT work_id FROM work_resources WHERE resource_id=?",
                        (c["entity_id"],),
                    )
                    if r[0] in linked
                )
        query = " ".join(
            direction.get(k, "") for k in ("title", "question", "method", "setting")
        )
    else:
        linked = []
        if not mandatory:
            mandatory.extend(
                r[0]
                for r in db.execute(
                    """SELECT DISTINCT r.work_id FROM reading_record_runs x JOIN reading_records r
                             ON r.id=x.record_id WHERE x.run_id=? AND r.recorded_at<=?""",
                    (run["id"], cutoff),
                )
            )
        query = ""
    # Retrieve even analyses which have never been cited in a direction or report.
    for wid in dict.fromkeys(mandatory):
        w = db.execute("SELECT title FROM works WHERE id=?", (wid,)).fetchone()
        if w:
            query += " " + w[0]
        rec = db.execute(
            "SELECT topic FROM reading_records WHERE work_id=? AND recorded_at<=? ORDER BY recorded_at DESC LIMIT 1",
            (wid, cutoff),
        ).fetchone()
        if rec and rec[0]:
            query += " " + rec[0]
    related = history_matches(db, query, cutoff) if query else []
    pinned = {c["version"] for c in changes if c["kind"] == "reading"}
    papers = {}
    for wid in dict.fromkeys([*mandatory, *linked[:9], *related]):
        paper = paper_material(db, wid, cutoff, pinned)
        if paper:
            paper["retrieval_role"] = (
                "本次材料"
                if wid in mandatory
                else "已关联方向"
                if wid in linked
                else "历史近邻候选"
            )
            papers[wid] = paper
    return papers


def signature(direction, profile, scope, papers, jobs, versions, results):
    work_state = [
        (
            wid,
            p["revision_id"],
            sorted(r["id"] for r in p["reading_records"]),
            sorted(r["record_id"] for r in p.get("historical_comparison", [])),
            [
                (r["id"], r["status"], r["revision_id"], r["details"])
                for r in p["resources"]
            ],
        )
        for wid, p in sorted(papers.items())
    ]
    artifacts = [
        (wid, a["id"], a["version"], a["evidence_id"])
        for wid, p in sorted(papers.items())
        for a in p["artifacts"]
    ]
    return key(
        "direction-assessment-v3",
        direction,
        profile,
        scope,
        work_state,
        artifacts,
        sorted(j["id"] for j in jobs),
        versions,
        results,
    )
