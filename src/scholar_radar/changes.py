"""Route durable research-input changes to the affected questions."""
from contextvars import ContextVar
from datetime import datetime
from zoneinfo import ZoneInfo

from .db import key,rows
from .discovery import sources
from .profile import get_profile
from .queue import job
from .settings import dump,now

current_run=ContextVar("research_change_run", default=None)
RESEARCH_STAGES=("assess","review","revise","publish","archive")


def work_directions(db,wid):
    return {r[0] for r in db.execute("""SELECT direction_id FROM memberships WHERE work_id=?
        UNION SELECT rd.direction_id FROM reading_records rr JOIN reading_record_directions rd ON rd.record_id=rr.id WHERE rr.work_id=?
        UNION SELECT s.dir_id FROM documents d JOIN revisions v ON v.document_id=d.id JOIN evidence e ON e.revision_id=v.id
              JOIN snapshot_evidence se ON se.evidence_id=e.id JOIN snapshots s ON s.id=se.snapshot_id WHERE d.work_id=?""",(wid,wid,wid))}


def update_run(db):
    active=current_run.get()
    if active and active["kind"] in {"daily","research_update"}:
        return active["id"]
    profile=get_profile(db)
    day=datetime.now(ZoneInfo(profile["timezone"])).date().isoformat()
    scope=sources()["scope_version"]
    existing=db.execute("""SELECT id FROM runs WHERE kind IN ('daily','research_update')
         AND as_of=? AND profile_id=? AND scope=? ORDER BY created_at DESC LIMIT 1""",(day,profile["id"],scope)).fetchone()
    if existing: return existing[0]
    rid=key("research update",day,profile["id"],scope)
    db.execute("""INSERT INTO runs(id,kind,as_of,profile_id,scope,status,created_at,detail)
        VALUES(?,'research_update',?,?,?,'queued',?,?)""",(rid,day,profile["id"],scope,now(),dump({"cold":False})))
    return rid


def arrange(db,rid,stages=RESEARCH_STAGES):
    for stage in stages:
        jid=job(db,rid,stage)
        db.execute("UPDATE jobs SET status='queued',outcome=NULL WHERE id=? AND status IN ('done','failed')",(jid,))
    db.execute("UPDATE runs SET status='queued',ended_at=NULL WHERE id=? AND status NOT IN ('running','queued')",(rid,))


def invalidate(db,kind,entity_id,version,direction_ids=None):
    if direction_ids is not None:
        targets=set(direction_ids)
    elif kind=="reading":
        targets=work_directions(db,entity_id) or {""}
    elif kind=="resource":
        targets=set()
        for r in db.execute("SELECT work_id FROM work_resources WHERE resource_id=?",(entity_id,)):
            targets.update(work_directions(db,r[0]))
    elif kind in {"definition","experiment","arc_result"}:
        targets={entity_id}
    else:
        targets=set()
    inserted=[]
    for did in sorted(targets):
        if did and not db.execute("SELECT 1 FROM directions WHERE id=? AND status!='merged'",(did,)).fetchone():
            continue
        cid=key("research-input",kind,entity_id,version,did)
        new=db.execute("INSERT OR IGNORE INTO direction_changes VALUES(?,?,?,?,?,?,NULL)",
                       (cid,kind,entity_id,version,did,now())).rowcount
        if new: inserted.append(did)
    if inserted: arrange(db,update_run(db))
    return inserted


def pending(db,direction_ids=None):
    result=rows(db,"SELECT * FROM direction_changes WHERE handled_at IS NULL ORDER BY rowid")
    return result if direction_ids is None else [x for x in result if x["direction_id"] in direction_ids]


def consume(db,ids):
    db.executemany("UPDATE direction_changes SET handled_at=? WHERE id=? AND handled_at IS NULL",((now(),cid) for cid in ids))


def input_versions(db,did):
    return rows(db,"""SELECT kind,entity_id,version FROM direction_changes WHERE rowid IN
           (SELECT max(rowid) FROM direction_changes WHERE direction_id=? GROUP BY kind,entity_id)
           ORDER BY kind,entity_id""",(did,))
