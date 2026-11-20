import json
import re
from urllib.parse import urlsplit

from .db import key
from .settings import dump, now

ARXIV = re.compile(r"(?:arxiv:|arxiv\.org/(?:abs|pdf)/)?((?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7}))(v\d+)?(?:\.pdf)?$", re.I)


def arxiv_id(value):
    m = ARXIV.search(str(value or "").strip().split("?")[0])
    return (m[1].lower(), m[2] or "") if m else (None, "")


def work(db, title, ids, meta=None):
    normalized = set()
    for ns, val in ids.items():
        if not val:
            continue
        val = str(val).strip()
        if ns == "arxiv":
            val = arxiv_id(val)[0]
        elif ns == "doi":
            val = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", val, flags=re.I).lower()
        if val:
            normalized.add((ns,val))
    if not normalized:
        raise ValueError("作品缺少稳定的外部身份")
    matches = {r[0] for ident in normalized for r in db.execute(
        "SELECT work_id FROM identifiers WHERE namespace=? AND value=?",ident)}
    if len(matches)>1:
        raise ValueError("作品身份冲突，需核对")
    wid = next(iter(matches)) if matches else key("work",sorted(normalized))
    db.execute("INSERT OR IGNORE INTO works VALUES(?,?,?,?)",(wid,title,now(),dump(meta or {})))
    for ns,val in sorted(normalized):
        db.execute("INSERT OR IGNORE INTO identifiers VALUES(?,?,?)",(ns,val,wid))
    return wid


def revision(db, wid, url, kind, upstream, body, *, version=None, mode="text", total=None,
             source_call=None, ranges=None):
    if urlsplit(url).scheme not in {"http","https"}:
        raise ValueError("原始来源需要 HTTP(S) URL")
    did = key("document",url,kind)
    rid = key("revision",did,upstream,mode)
    total = len(body) if total is None else total
    ranges = [[0,len(body)]] if ranges is None else ranges
    db.execute("INSERT OR IGNORE INTO documents VALUES(?,?,?,?)",(did,wid,url,kind))
    old = db.execute("SELECT body FROM revisions WHERE id=?",(rid,)).fetchone()
    if old and body!=old[0] and not body.startswith(old[0]):
        raise ValueError("同一文档修订的文本与原记录冲突")
    if not old:
        db.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (rid,did,upstream,mode,version,now(),body,total,dump(ranges),source_call))
    elif len(body)>len(old[0]):
        db.execute("UPDATE revisions SET body=?,total_chars=?,coverage=? WHERE id=?",(body,total,dump(ranges),rid))
    if not old or len(body)>len(old[0]):
        db.execute("DELETE FROM revision_search WHERE id=?",(rid,))
        db.execute("INSERT INTO revision_search VALUES(?,?)",(rid,body))
    return rid


def span(db, rid, start, end, quote, stance="supports"):
    row=db.execute("SELECT body,coverage FROM revisions WHERE id=?",(rid,)).fetchone()
    if (not row or not quote.strip() or not 0<=start<end<=len(row["body"]) or
        row["body"][start:end]!=quote or not any(a<=start and end<=b for a,b in json.loads(row["coverage"]))):
        raise ValueError("引用文本、字符位置或读取范围与文档修订不符")
    eid=key("evidence",rid,start,end)
    db.execute("INSERT OR IGNORE INTO evidence VALUES(?,?,?,?,?,?,?,?)",
               (eid,rid,start,end,quote,row["body"].count("\n",0,start)+1,
                row["body"].count("\n",0,end-1)+1,stance))
    return eid


def claim(db, kind, statement, ids, allowed, conditions=None):
    if not ids or not set(ids)<=set(allowed):
        raise ValueError("主张引用了任务范围外的证据")
    cid=key(kind,statement,sorted(ids),conditions)
    db.execute("INSERT OR IGNORE INTO claims VALUES(?,?,?,?)",(cid,kind,statement,dump(conditions or {})))
    for eid in ids:
        db.execute("INSERT OR IGNORE INTO claim_evidence VALUES(?,?)",(cid,eid))
    return cid


def resource(db,wid,url,kind,relation="author_link"):
    if urlsplit(url).scheme not in {"https","http"}:
        return
    resource_id=key("resource",url)
    db.execute("INSERT OR IGNORE INTO resources VALUES(?,?,?)",(resource_id,url,kind))
    db.execute("INSERT OR IGNORE INTO work_resources VALUES(?,?,?)",(wid,resource_id,relation))
