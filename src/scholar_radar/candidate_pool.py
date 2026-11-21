import json
from .db import key,rows
from .settings import dump,now


def remember(db,p):
    wid=p["work_id"]
    old=db.execute("SELECT body FROM candidate_inventory WHERE work_id=?",(wid,)).fetchone()
    body=json.loads(old[0]) if old else {}
    for name,value in p.items():
        if value not in (None,"",[]):
            if name=="abstract" and len(value)<len(body.get("abstract") or ""): continue
            body[name]=value
    version=key(body.get("title"),body.get("abstract"),body.get("arxiv_id"),body.get("doi"),body.get("published_date"),body.get("pdf_url"))
    db.execute("""INSERT INTO candidate_inventory VALUES(?,?,?,?,?) ON CONFLICT(work_id) DO UPDATE SET
        last_seen=excluded.last_seen,version=excluded.version,body=excluded.body""",(wid,now(),now(),version,dump(body)))


def eligible(db,profile_id,scope,limit,preferred=()):
    if limit<=0: return []
    sql="""SELECT ci.*,w.title FROM candidate_inventory ci JOIN works w ON w.id=ci.work_id
        WHERE NOT EXISTS(SELECT 1 FROM reading_records rr WHERE rr.work_id=ci.work_id)
        AND NOT EXISTS(SELECT 1 FROM readings l WHERE json_extract(l.paper,'$.work_id')=ci.work_id AND l.status IN ('queued','done'))
        AND NOT EXISTS(SELECT 1 FROM candidate_decisions s WHERE s.work_id=ci.work_id AND s.profile_id=? AND s.scope=? AND s.version=ci.version)"""
    params=[profile_id,scope]
    priority=[]
    if preferred:
        preferred=list(dict.fromkeys(preferred))[:120]
        priority=rows(db,sql+" AND ci.work_id IN ("+",".join("?" for _ in preferred)+") ORDER BY ci.last_seen DESC,ci.work_id LIMIT ?",
                      [*params,*preferred,max(1,limit//2)])
    rest=rows(db,sql+" ORDER BY ci.first_seen,ci.work_id LIMIT ?",[*params,limit+len(priority)])
    choices={}
    for v in priority+rest:
        p=json.loads(v["body"])
        if p.get("arxiv_id") or p.get("doi") or p.get("s2_id") or p.get("paper_id"):
            choices.setdefault(v["work_id"],{**p,"work_id":v["work_id"],"title":v["title"],"inventory_version":v["version"]})
        if len(choices)>=limit: break
    return list(choices.values())


def mark(db,run,batch,selected):
    chosen={p["work_id"]:p for p in selected}
    for p in batch:
        item=chosen.get(p["work_id"])
        db.execute("INSERT OR IGNORE INTO candidate_decisions VALUES(?,?,?,?,?,?,?,?)",
            (p["work_id"],run["profile_id"],run["scope"],p["inventory_version"],run["id"],
             "selected" if item else "considered",item.get("selection_reason","") if item else "",now()))
