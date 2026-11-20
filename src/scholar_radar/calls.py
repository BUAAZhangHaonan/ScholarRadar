import asyncio
import json
import re
from pathlib import Path

from . import mcp_client
from .db import database, key
from .settings import VAR, atomic_text, dump, now


class CallUnavailable(RuntimeError):
    pass


def _money(value):
    return float(value) if value is not None else None


def record_receipt(db, cid, data, recovered=False):
    cost = data.get("cost") or data.get("usage_cost") or {}
    if not isinstance(cost,dict):
        cost = {}
    reused = bool(cost.get("reused_result") or data.get("analysis_reused"))
    original = data.get("original_cost") if reused else None
    historical_cost = original if isinstance(original,dict) else cost
    attempts = historical_cost.get("attempts") or []
    units = attempts or [historical_cost]
    for i, unit in enumerate(units):
        provider_id = unit.get("request_id") or unit.get("provider_request_id")
        receipt_id = key("provider",provider_id,unit.get("model_returned")) if provider_id else key(cid,i)
        if reused and not recovered and original:
            receipt_id=key("historical",cid,i)
        lo, hi = _money(unit.get("lower_cny")), _money(unit.get("upper_cny"))
        amount = _money(unit.get("total_cny"))
        if amount is None and lo is not None and lo==hi:
            amount = lo
        historical = amount if reused else None
        # A recovered local dispatch owns its original cost; a cache hit without
        # an earlier local dispatch only exposes the upstream historical charge.
        if reused and not recovered:
            amount = lo = hi = 0.0
        db.execute("INSERT OR IGNORE INTO receipts VALUES(?,?,?,?,?,?,?,?,?)",
                   (receipt_id,cid,cost.get("currency"),amount,lo,hi,historical,
                    dump(unit.get("usage")),dump(unit)))


async def invoke(service, tool, args, *, identity, run_id=None, id_field=None, transport=None, safe=False):
    cid = key(service,tool,identity,args)
    supplied = dict(args)
    if id_field:
        supplied[id_field] = "radar-"+cid
    result_path = VAR / "responses" / (cid+".json")
    with database(write=True) as db:
        row = db.execute("SELECT * FROM calls WHERE id=?", (cid,)).fetchone()
        if not row:
            db.execute("INSERT INTO calls(id,service,tool,args,remote_id,status,started_at) VALUES(?,?,?,?,?,'prepared',?)",
                       (cid,service,tool,dump(supplied),supplied.get(id_field),now()))
        if run_id:
            db.execute("INSERT OR IGNORE INTO run_calls VALUES(?,?,?)",(run_id,cid,int(bool(row and row["status"]=="done"))))
        if row and row["status"]=="done":
            return json.loads(Path(row["file"]).read_text())
        if row and row["status"]=="failed":
            transient = bool(re.search(r"\b(429|502|503|504)\b", row["error"] or ""))
            previous = list(result_path.parent.glob(cid+".failed-*.json"))
            if not (safe and transient and len(previous)<2):
                raise CallUnavailable(row["error"] or "上游业务失败")
            if result_path.exists():
                result_path.replace(result_path.with_name(cid+f".failed-{len(previous)+1}.json"))
        recovered = bool(row and row["status"] in ("sent","unknown_outcome"))
        if recovered and not (id_field or safe or result_path.exists()):
            raise CallUnavailable("上游结果尚未确认，保留原请求")
        db.execute("UPDATE calls SET status='sent' WHERE id=?", (cid,))
    try:
        if result_path.exists():
            result = json.loads(result_path.read_text())
        else:
            result = await (transport(supplied) if transport else mcp_client.call(service,tool,supplied))
            if not isinstance(result,dict):
                raise ValueError("返回体需要对象")
            atomic_text(result_path,dump(result))
    except BaseException as exc:
        with database(write=True) as db:
            db.execute("UPDATE calls SET status='unknown_outcome',error=? WHERE id=?",(type(exc).__name__,cid))
        raise
    error = result.get("error") or (result.get("status") if str(result.get("status","")).lower() in
            {"error","failed","failure","unauthorized","invalid_request","timeout"} else None)
    with database(write=True) as db:
        record_receipt(db,cid,result,recovered)
        db.execute("UPDATE calls SET status=?,ended_at=?,file=?,error=? WHERE id=?",
                   ("failed" if error else "done",now(),str(result_path),str(error)[:300] if error else None,cid))
    if error:
        raise CallUnavailable(str(error)[:300])
    return result
