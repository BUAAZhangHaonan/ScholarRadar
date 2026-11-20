import asyncio
import fcntl
import json
import os
import socket
from datetime import datetime,UTC

from .acquisition import collect,screen,reading
from .archive import archive_run
from .assessment import assess
from .db import database,migrate
from .mcp_client import inventory
from .observation import observe
from .official import postings
from .queue import take,finish,schedule
from .registry import initialize
from .reports import publish
from .settings import VAR,now

STAGES={"discover":collect,"official":postings,"observe":observe,"screen":screen,
        "read":reading,"assess":assess,"publish":publish,"archive":archive_run}


async def heartbeat(jid,owner):
    while True:
        await asyncio.sleep(30)
        with database(write=True) as db:
            db.execute("UPDATE jobs SET lease_at=? WHERE id=? AND owner=? AND status='working'",(now(),jid,owner))


async def execute(run,job,owner):
    beat=asyncio.create_task(heartbeat(job["id"],owner))
    try:
        if job["stage"]=="discover": await inventory()
        handler=STAGES[job["stage"]]
        detail=await (handler(run,json.loads(job["payload"])) if job["stage"]=="read" else handler(run))
        ok=True
    except Exception as exc:
        detail={"error_type":type(exc).__name__,"error":str(exc)[:320]}
        ok=False
    finally:
        beat.cancel()
        await asyncio.gather(beat,return_exceptions=True)
    with database(write=True) as db: finish(db,run["id"],job["id"],ok,detail)
    print(run["id"],job["stage"],"done" if ok else "failed",flush=True)


async def worker(once=False):
    migrate()
    owner=socket.gethostname()+":"+str(os.getpid())
    with (VAR/"worker.lock").open("a+") as lock:
        while True:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if once: return
                await asyncio.sleep(5)
        with database(write=True) as db: initialize(db)
        tick=None
        while True:
            current=datetime.now(UTC)
            with database(write=True) as db:
                minute=current.strftime("%Y%m%d%H%M")
                if tick!=minute:
                    schedule(db,current)
                    tick=minute
                pair=take(db,owner)
            if pair:
                await execute(*pair,owner)
            elif once:
                return
            else:
                await asyncio.sleep(3)
