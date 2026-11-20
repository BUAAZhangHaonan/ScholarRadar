import asyncio
import json
import xml.etree.ElementTree as ET
from datetime import date,datetime,timedelta,UTC

import asyncpg
import httpx

from .acquisition import coverage
from .db import database,key
from .discovery import sources
from .evidence import arxiv_id,work
from .queue import job
from .settings import VAR,atomic_text,deployment,dump,now

ATOM="{http://www.w3.org/2005/Atom}"
MIRROR_RULE="固定分类 cs.CL/AI/CV/LG 与标题 hallucination / instruction following / tool use / selective prediction"


async def mirror_window(start,end):
    c=await asyncpg.connect(deployment()["mirror_dsn"],timeout=6,
                            server_settings={"default_transaction_read_only":"on","statement_timeout":"20000"})
    try:
        async with c.transaction(readonly=True,isolation="repeatable_read"):
            sync=await c.fetch("SELECT name,status,last_response_date,last_success_at FROM sync_state")
            papers=await c.fetch("""SELECT id,title,abstract,doi,latest_version,first_version_date,latest_version_date,
                     authors FROM arxiv_papers WHERE categories && ARRAY['cs.CL','cs.AI','cs.CV','cs.LG']::text[]
                     AND title ILIKE ANY(ARRAY['%hallucination%','%instruction following%','%tool use%','%selective prediction%'])
                     AND ((first_version_date >= $1 AND first_version_date < $2) OR
                          (latest_version_date >= $1 AND latest_version_date < $2)) ORDER BY id""",start,end)
        return [{k:(v.isoformat() if hasattr(v,"isoformat") else v) for k,v in dict(row).items()} for row in papers],[
            {k:(v.isoformat() if hasattr(v,"isoformat") else v) for k,v in dict(row).items()} for row in sync]
    finally:
        await c.close()


def parse_atom(text):
    root=ET.fromstring(text)
    papers=[]
    for entry in root.findall(ATOM+"entry"):
        field=lambda n:entry.findtext(ATOM+n,"").strip()
        base,version=arxiv_id(field("id"))
        if not base: raise ValueError("Atom 返回的标识不是论文")
        papers.append({"id":base,"latest_version":int(version[1:]) if version else None,"title":field("title"),
                       "abstract":field("summary"),"first_version_date":field("published"),"latest_version_date":field("updated"),
                       "authors":[a.findtext(ATOM+"name","") for a in entry.findall(ATOM+"author")]})
    return papers


async def coordinated_stream(gateway,stream,start,end,run_id):
    query=sources()["arxiv_query"]
    if stream=="submitted":
        query+=f" AND submittedDate:[{start:%Y%m%d}0000 TO {(end-timedelta(days=1)):%Y%m%d}2359]"
    order="submittedDate" if stream=="submitted" else "lastUpdatedDate"
    records=[]; offset=0
    from .calls import invoke
    async with httpx.AsyncClient(timeout=50) as client:
        async def atom_page(args):
            response=await client.get(gateway,params=args)
            response.raise_for_status()
            return {"atom":response.text,"cost":{"basis":"no_paid_calls","total_cny":0,"lower_cny":0,"upper_cny":0,"currency":"CNY"}}
        for _ in range(25):
            params={"search_query":query,"sortBy":order,"sortOrder":"descending","start":offset,"max_results":100}
            result=await invoke("arxiv","atom_page",params,identity=["arxiv-v1",sources()["scope_version"],stream,str(start),str(end)],
                                run_id=run_id,transport=atom_page,safe=True)
            page=parse_atom(result["atom"])
            stamp="first_version_date" if stream=="submitted" else "latest_version_date"
            records.extend(p for p in page if str(start)<=p[stamp][:10]<str(end))
            offset+=len(page)
            if len(page)<100 or (page and page[-1][stamp][:10]<str(start)): return records,True,offset
            await asyncio.sleep(3.1)
    return records,False,offset


async def observe(run):
    rid=run["id"]; day=date.fromisoformat(run["as_of"]); end=day+timedelta(days=1)
    cfg=deployment(); scope=run["scope"]
    cold=json.loads(run["detail"])["cold"]
    gateway=cfg.get("coordinated_arxiv_url") if cfg.get("all_arxiv_clients_coordinated") else None
    for stream in ("submitted","updated"):
        source="arXiv shared gateway" if gateway else "arXiv local mirror"
        with database() as db:
            last=db.execute("SELECT watermark FROM cursors WHERE source=? AND scope=? AND stream=?",(source,scope,stream)).fetchone()
        start=day-timedelta(days=90 if cold else 3)
        if last: start=min(day,date.fromisoformat(last[0][:10]))-timedelta(days=2)
        if gateway:
            papers,complete,offset=await coordinated_stream(gateway,stream,start,end,rid)
            reason=None if complete else "分页达到任务上限"
        else:
            papers,sync=await mirror_window(start,end)
            stamp="first_version_date" if stream=="submitted" else "latest_version_date"
            papers=[p for p in papers if p.get(stamp) and str(start)<=p[stamp][:10]<str(end)]
            complete=False; offset=len(papers)
            reason="本地镜像没有可验证的完整窗口与跨服务统一接入记录"
        raw=VAR/"observations"/(key(rid,stream)+".json")
        atomic_text(raw,dump({"stream":stream,"papers":papers,"scope":scope,"query":MIRROR_RULE,"start":str(start),"end":str(end)}))
        with database(write=True) as db:
            for p in papers:
                wid=work(db,p["title"],{"arxiv":p["id"],"doi":p.get("doi")},p)
                version="v"+str(p["latest_version"]) if p.get("latest_version") else None
                event="first_submission" if stream=="submitted" else "version_update"
                stamp=p.get("first_version_date") if stream=="submitted" else p.get("latest_version_date")
                db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (key(wid,event,stamp,version if stream=="updated" else None),wid,event,version,p.get("first_version_date"),
                     p.get("latest_version_date"),None,now(),now(),"https://arxiv.org/abs/"+p["id"]))
                if stream=="updated" and version:
                    tracked=db.execute("SELECT 1 FROM documents WHERE work_id=?",(wid,)).fetchone()
                    already=db.execute("SELECT 1 FROM documents d JOIN revisions v ON v.document_id=d.id WHERE d.work_id=? AND v.version=?",(wid,version)).fetchone()
                    if tracked and not already:
                        versioned=p["id"]+version
                        material={**p,"arxiv_id":versioned,"work_id":wid,"canonical_url":"https://arxiv.org/abs/"+versioned,"version_event":True}
                        db.execute("INSERT OR IGNORE INTO readings VALUES(?,?,?,'queued','{}')",(rid,versioned,dump(material)))
                        job(db,rid,"read",{"key":versioned})
                if stream=="submitted":
                    db.execute("INSERT OR IGNORE INTO observed VALUES(?,?,?,?,?,NULL)",(source,scope,stamp,wid,version or "unknown"))
            coverage(db,rid,source,"observation",scope,stream,start,end,len(papers),len({p["id"] for p in papers}),
                     "ok" if complete else "partial",complete=complete,cursor=str(offset),path=str(raw),reason=reason)
            if complete:
                db.execute("INSERT OR REPLACE INTO cursors VALUES(?,?,?,?)",(source,scope,stream,str(end)))
    if complete:
        from .classification import classify
        await classify(run)
    return {"scope":scope,"source":source,"complete":complete,"reason":reason}
