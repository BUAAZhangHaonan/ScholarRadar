import re
from datetime import date
from urllib.parse import urlsplit

from .acquisition import coverage
from .calls import invoke
from .db import database,key
from .discovery import official_page,sources
from .evidence import revision,span
from .settings import dump,now


def trusted(url):
    p=urlsplit(url); host=(p.hostname or "").lower()
    return p.scheme=="https" and not p.username and not p.password and any(
        host==d or host.endswith("."+d) for d in sources()["official_domains"])


async def postings(run):
    day=date.fromisoformat(run["as_of"]); rid=run["id"]; url=sources()["official_job"]
    with database() as db:
        prior=[r[0] for r in db.execute("SELECT url FROM postings ORDER BY first_seen DESC LIMIT 3")]
    urls=list(dict.fromkeys([url,*prior]))
    search_query="北京 多模态 大语言模型 后训练 研究实习 岗位 site:microsoft.com/en-us/research/opportunity/"
    try:
        hits=await invoke("web","web_search",{"query":search_query,"max_results":5},identity=["jobs-v1",str(day)],
                          run_id=rid,safe=True)
        links=hits.get("results") or hits.get("items") or []
        for hit in links:
            u=hit.get("url","")
            if trusted(u) and "/research/opportunity/" in u and u not in urls:
                urls.append(u)
    except Exception as exc:
        with database(write=True) as db:
            coverage(db,rid,"web-research","discovery",run["scope"],search_query,day,day,None,None,"failed",reason=str(exc)[:200])
    valid=0
    # Verify a bounded number of official pages on each date.
    for u in urls[:1 if __import__("json").loads(run["detail"])["cold"] else 3]:
        pid=key("official",u)
        try:
            page=await official_page(u,day,rid)
            if not trusted(page.get("final_url") or u): raise ValueError("跳转到未核实的域名")
            body=page.get("text") or ""
            if not body.strip(): raise ValueError("缺少官方职位正文")
            title=(page.get("title") or body.splitlines()[0]).split(" - Microsoft Research")[0].strip()
            with database(write=True) as db:
                row=db.execute("SELECT organization_id FROM aliases WHERE alias='MSRA'").fetchone()
                org=row[0] if "microsoft.com/" in u and row else None
                src=key("web","fetch_page",["official",str(day),u],{"url":u,"max_chars":20000,"refresh":True})
                rv=revision(db,None,u,"job",page["version"],body,total=page["total_chars"],source_call=src)
                db.execute("INSERT OR IGNORE INTO postings VALUES(?,?,NULL,?,?,?,NULL)",(pid,org,u,title,now()))
                linked=[]
                for m in re.finditer(r"[^\n]+",body):
                    if 15<=len(m[0])<=1050 and re.search(
                        r"(?i)location|beijing|candidate|knowledge|experience|proficien|qualif|machine learning|reinforcement learning|language model|申请要求|熟悉|北京",m[0]):
                        linked.append(span(db,rv,m.start(),m.end(),m[0]))
                        if len(linked)>=12: break
                closed=bool(re.search(r"(position (?:is |has been )?(?:closed|filled)|no longer accepting applications|岗位已关闭)",body,re.I))
                status="closed" if closed else ("advertised" if re.search(r"(?i)apply|application|招聘|申请",body) else "unknown")
                db.execute("INSERT OR IGNORE INTO posting_observations VALUES(?,?,?,?,?,?)",
                           (key(pid,str(day),rv),pid,rv,now(),status,dump({"evidence_ids":linked,"identity":"official_url"})))
                coverage(db,rid,"官方岗位","discovery",run["scope"],u,day,day,1,1,"ok",reason="官方详情单独核验")
                valid+=1
        except Exception as exc:
            with database(write=True) as db:
                if db.execute("SELECT 1 FROM postings WHERE id=?",(pid,)).fetchone():
                    db.execute("INSERT OR IGNORE INTO posting_observations VALUES(?,?,NULL,?,'unavailable',?)",
                               (key(pid,str(day),"unavailable"),pid,now(),dump({"reason":str(exc)[:200]})))
                coverage(db,rid,"官方岗位","discovery",run["scope"],u,day,day,None,None,"unavailable",reason=str(exc)[:200])
    return {"verified":valid,"discovered_urls":len(urls)}
