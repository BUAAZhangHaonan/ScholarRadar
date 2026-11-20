import json
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .db import database,key
from .discovery import sources
from .profile import get_profile
from .settings import dump, now

ORDER=("discover","official","observe","screen","read","assess","publish","archive")


def job(db,rid,stage,payload=None):
    payload=payload or {}
    jid=key(rid,stage,payload)
    db.execute("INSERT OR IGNORE INTO jobs(id,run_id,stage,payload,status,created_at) VALUES(?,?,?,?,'queued',?)",
               (jid,rid,stage,dump(payload),now()))
    return jid


def enqueue(db,kind,day):
    if kind not in ("daily","weekly","monthly"): raise ValueError("不支持的任务")
    p=get_profile(db); scope=sources()["scope_version"]
    rid=key("run",kind,str(day),p["id"],scope)
    if db.execute("SELECT 1 FROM runs WHERE id=?",(rid,)).fetchone(): return rid
    cold=not bool(db.execute("SELECT 1 FROM reports WHERE kind='daily' LIMIT 1").fetchone())
    db.execute("INSERT INTO runs(id,kind,as_of,profile_id,scope,status,created_at,detail) VALUES(?,?,?,?,?,'queued',?,?)",
               (rid,kind,str(day),p["id"],scope,now(),dump({"cold":cold})))
    stages=ORDER if kind=="daily" else ("publish","archive")
    for stage in stages:
        if stage!="read": job(db,rid,stage)
    return rid


def schedule(db,instant,limit=7):
    profile=get_profile(db); tz=ZoneInfo(profile["timezone"])
    local=instant.astimezone(tz)
    hh,mm=map(int,profile["daily_time"].split(":"))
    due=local.date() if (local.hour,local.minute)>=(hh,mm) else local.date()-timedelta(days=1)
    row=db.execute("SELECT min(as_of),max(as_of) FROM runs WHERE kind='daily'").fetchone()
    first=date.fromisoformat(row[0]) if row[0] else local.date()
    start=max(first,due-timedelta(days=limit-1))
    for d in (start+timedelta(days=i) for i in range(max(0,(due-start).days+1))):
        enqueue(db,"daily",d)
        if d.weekday()==profile["weekly_day"]: enqueue(db,"weekly",d)
        if d.day==profile["monthly_day"]: enqueue(db,"monthly",d)


def take(db,owner):
    active=list(db.execute("SELECT * FROM runs WHERE status IN ('queued','running') ORDER BY as_of,CASE kind WHEN 'daily' THEN 0 ELSE 1 END,created_at"))
    for run in active:
        for stage in ORDER:
            waiting=db.execute("SELECT * FROM jobs WHERE run_id=? AND stage=? AND status IN ('queued','working') ORDER BY created_at,rowid LIMIT 1",(run["id"],stage)).fetchone()
            if not waiting: continue
            db.execute("UPDATE jobs SET status='working',owner=?,lease_at=?,attempts=attempts+1 WHERE id=?",
                       (owner,now(),waiting["id"]))
            db.execute("UPDATE runs SET status='running',started_at=COALESCE(started_at,?) WHERE id=?",(now(),run["id"]))
            return dict(run),dict(waiting)
    return None


def finish(db,rid,jid,ok,detail):
    db.execute("UPDATE jobs SET status=?,outcome=?,lease_at=? WHERE id=?",
               ("done" if ok else "failed",dump(detail),now(),jid))
    left=db.execute("SELECT count(*) FROM jobs WHERE run_id=? AND status IN ('queued','working')",(rid,)).fetchone()[0]
    if not left:
        failed=db.execute("SELECT count(*) FROM jobs WHERE run_id=? AND status='failed'",(rid,)).fetchone()[0]
        partial=db.execute("SELECT 1 FROM coverage WHERE run_id=? AND status IN ('partial','failed','unavailable')",(rid,)).fetchone()
        db.execute("UPDATE runs SET status=?,ended_at=? WHERE id=?",("partial" if failed or partial else "done",now(),rid))
