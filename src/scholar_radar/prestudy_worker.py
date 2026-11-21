import asyncio
import json
import os
from pathlib import Path

from .db import database
from .settings import ROOT,VAR,dump,now


async def command(cfg,operation,hid,stdin=None):
    exe=Path(cfg["executable"]).resolve()
    if not exe.is_file(): raise ValueError("ARC 的部署程序不可用")
    args=[str(exe),"--config",cfg["config"],"--env-file",cfg["env_file"],"--data-dir",cfg["data_dir"],"handoff",operation]
    if operation!="import": args.append(hid)
    logs=VAR/"arc-logs";logs.mkdir(mode=0o700,parents=True,exist_ok=True)
    cache=VAR/"arc-cache";cache.mkdir(mode=0o700,parents=True,exist_ok=True)
    env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1","TMPDIR":str(VAR/"staging"),"XDG_CACHE_HOME":str(cache)}
    with (logs/(hid+".log")).open("ab") as err:
        process=await asyncio.create_subprocess_exec(*args,cwd=cfg.get("cwd") or ROOT,env=env,stdin=asyncio.subprocess.PIPE,
                              stdout=asyncio.subprocess.PIPE,stderr=err)
        out,_=await process.communicate(dump(stdin).encode() if stdin is not None else None)
    if process.returncode: raise RuntimeError("ARC "+operation+" 未完成，可用同一提交查询状态")
    data=json.loads(out)
    if data.get("handoff_id")!=hid or data.get("schema_version")!="radar.arc.prestudy.v1":
        raise ValueError("ARC 返回的运行身份或协议不匹配")
    return data


def save_result(hid,data):
    with database(write=True) as db:
        h=db.execute("SELECT * FROM arc_handoffs WHERE id=?",(hid,)).fetchone()
        if data["origin"]["snapshot_id"]!=h["snapshot_id"] or data["origin"]["direction_id"]!=h["direction_id"] or (h["arc_run_id"] and h["arc_run_id"]!=data["run_id"]):
            raise ValueError("ARC 结果不属于选定的方向与阶段")
        status=data["execution_status"]
        db.execute("UPDATE arc_handoffs SET idea_id=?,arc_run_id=?,status=?,result_json=?,updated_at=?,error=NULL WHERE id=?",
                   (data["idea_id"],data["run_id"],status,dump(data),now(),hid))
        if status=="completed" and data.get("current_understanding"):
            from .changes import invalidate
            invalidate(db,"arc_result",h["direction_id"],hid,[h["direction_id"]])


async def execute(run,payload):
    hid=payload["handoff_id"]
    with database() as db: h=db.execute("SELECT * FROM arc_handoffs WHERE id=?",(hid,)).fetchone()
    cfg=json.loads(h["runtime_json"])
    if h["status"]=="completed": return {"handoff_id":hid,"reused":True}
    try:
        result=await command(cfg,"result",hid) if h["arc_run_id"] else await command(cfg,"import",hid,json.loads(h["bundle_json"]))
        save_result(hid,result)
        if result["execution_status"] in {"prepared","running","paused_external"}:
            with database(write=True) as db: db.execute("UPDATE arc_handoffs SET status='running',updated_at=? WHERE id=?",(now(),hid))
            result=await command(cfg,"execute",hid)
            while result["execution_status"]=="running":
                await asyncio.sleep(12)
                result=await command(cfg,"result",hid)
            save_result(hid,result)
        if result["execution_status"]!="completed": raise StageStopped(result["execution_status"])
    except StageStopped:
        raise
    except Exception as exc:
        with database(write=True) as db:
            db.execute("UPDATE arc_handoffs SET status='connection_unknown',error=?,updated_at=? WHERE id=?",(str(exc)[:220],now(),hid))
        raise
    return {"handoff_id":hid,"arc_run_id":result["run_id"],"decision":result.get("research_decision")}


class StageStopped(RuntimeError):
    pass
