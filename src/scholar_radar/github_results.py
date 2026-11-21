"""Publish saved, readable research results without running research again."""

import base64
import json
import os
import re
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from .db import database
from .settings import deployment


LABELS = {"daily": "日报", "weekly": "周报", "monthly": "月报", "arc": "ARC 预研"}


class GitHubSyncUnavailable(RuntimeError):
    """A retry can publish the same saved result without repeating paid work."""


def configuration():
    try:
        return deployment().get("github_results") or {}
    except FileNotFoundError:
        return {}


def destination(cfg):
    return {"repository": cfg.get("repository", ""), "branch": cfg.get("branch", "")}


def enqueue_result(db, rid, kind, result_id, *, retry=False):
    cfg = configuration()
    if not cfg.get("enabled"):
        return None
    from .queue import job

    jid = job(db, rid, "github_sync", {
        "kind": kind, "result_id": result_id, **destination(cfg),
    })
    if retry:
        db.execute(
            "UPDATE jobs SET status='queued',attempts=0,outcome=NULL WHERE id=? AND status IN ('done','failed')",
            (jid,),
        )
    db.execute(
        "UPDATE runs SET status='queued',ended_at=NULL WHERE id=? AND status IN ('done','partial') "
        "AND EXISTS(SELECT 1 FROM jobs WHERE id=? AND status='queued')", (rid, jid),
    )
    return jid


def backfill(db):
    if not configuration().get("enabled"):
        raise ValueError("请先在 deployment.json 中启用 github_results 并指定结果仓库")
    saved = list(db.execute(
        "SELECT r.run_id,v.id FROM report_versions v JOIN reports r ON r.id=v.report_id ORDER BY v.generated_at,v.id"
    ))
    arcs = list(db.execute(
        "SELECT radar_run_id,id FROM arc_handoffs WHERE status='completed' AND result_json IS NOT NULL ORDER BY updated_at,id"
    ))
    for rid, result_id in saved:
        enqueue_result(db, rid, "report", result_id, retry=True)
    for rid, result_id in arcs:
        enqueue_result(db, rid, "arc", result_id, retry=True)
    return {"reports": len(saved), "arc_results": len(arcs)}


def saved_result(payload):
    from .result_markdown import render_arc, render_report

    result_id = payload["result_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", result_id):
        raise ValueError("结果编号无效")
    with database() as db:
        if payload["kind"] == "report":
            row = db.execute("SELECT body,rowid sequence FROM report_versions WHERE id=?", (result_id,)).fetchone()
            if not row:
                raise ValueError("报告历史版本不存在")
            report = json.loads(row[0])
            kind, day, stamp = report["kind"], report["date"], report["generated_at"]
            body = render_report(report)
            title = f"{day} · {LABELS[kind]}"
        elif payload["kind"] == "arc":
            row = db.execute("SELECT *,rowid sequence FROM arc_handoffs WHERE id=? AND status='completed'", (result_id,)).fetchone()
            if not row:
                raise ValueError("ARC 结果尚未完成")
            handoff = dict(row)
            kind, stamp = "arc", handoff["updated_at"]
            day = datetime.fromisoformat(stamp).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
            body = render_arc(handoff)
            stage = "展开研究方案" if handoff["stage"] == "develop" else "检查关键前提"
            title = f"{day} · {stage} · {handoff['focus']}"
        else:
            raise ValueError("不支持的归档结果")
    entry = {
        "id": f"{payload['kind']}:{result_id}", "kind": kind, "date": day,
        "generated_at": stamp, "sequence": row["sequence"], "title": title,
        "path": f"results/{kind}/{day}-{result_id}.md",
    }
    return entry, body


def ordered(entries):
    return sorted(entries, key=lambda x: (x["date"], x["generated_at"], x.get("sequence", 0), x["id"]), reverse=True)


def link(entry):
    title = re.sub(r"\s+", " ", entry["title"]).replace("[", "\\[").replace("]", "\\]")
    return f"[{title}]({entry['path'].removeprefix('results/')})"


def index_markdown(entries):
    return "\n".join([
        "# ScholarRadar 研究结果", "",
        "从 [最新结果](LATEST.md) 开始阅读。以下是每次整理时保存的判断，历史版本不会随之后的结论改写。", "",
        "## 历史结果", "", *[f"- {link(e)}" for e in entries], "",
    ])


def latest_markdown(entries, body):
    latest_by_kind = {}
    for entry in entries:
        latest_by_kind.setdefault(entry["kind"], entry)
    links = [f"- 最新{LABELS[kind]}：{link(e)}" for kind, e in latest_by_kind.items()]
    return "\n".join([
        "# ScholarRadar 最新结果", "", "[全部历史结果](README.md)", "", *links, "",
        "---", "", body.rstrip(), "",
    ])


async def request(client, method, path, *, missing=False, **kwargs):
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.TransportError:
        raise GitHubSyncUnavailable("GitHub 连接中断，已保存的结果等待补传") from None
    code = response.status_code
    if missing and code == 404:
        return None
    rate_limited = code == 403 and (
        response.headers.get("x-ratelimit-remaining") == "0" or response.headers.get("retry-after")
    )
    if code in (409, 422, 429) or code >= 500 or rate_limited:
        raise GitHubSyncUnavailable(f"GitHub 暂未接受提交（HTTP {code}），可重试同一结果")
    if code >= 400:
        raise ValueError(f"GitHub 请求失败（HTTP {code}），请检查目标仓库、分支和令牌的 Contents 写入权限")
    return response.json()


async def file_text(client, prefix, path, head, *, missing=False):
    data = await request(client, "GET", f"{prefix}/contents/{quote(path, safe='/')}",
                         params={"ref": head}, missing=missing)
    if data is None:
        return None
    if data.get("encoding") != "base64":
        raise ValueError("GitHub 结果文件无法按 UTF-8 文本读取")
    return base64.b64decode(data["content"]).decode("utf-8")


async def commit_result(client, cfg, entry, body):
    repository = cfg.get("repository", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("github_results.repository 需要 owner/repository 格式")
    prefix = f"/repos/{repository}"
    repo = await request(client, "GET", prefix)
    if not repo.get("private") and cfg.get("allow_public") is not True:
        raise ValueError("结果包含个人研究内容；请指定私有仓库，或明确设置 allow_public=true")
    branch = cfg.get("branch") or repo["default_branch"]
    ref = await request(client, "GET", f"{prefix}/git/ref/heads/{quote(branch, safe='/')}")
    head = ref["object"]["sha"]
    commit = await request(client, "GET", f"{prefix}/git/commits/{head}")
    base_tree = commit["tree"]["sha"]
    index = await file_text(client, prefix, "results/index.json", head, missing=True)
    catalog = json.loads(index) if index is not None else {"version": 1, "entries": []}
    if catalog.get("version") != 1 or not isinstance(catalog.get("entries"), list):
        raise ValueError("结果索引格式不兼容，未修改远端内容")
    entries = ordered([e for e in catalog["entries"] if e["id"] != entry["id"]] + [entry])
    latest = entries[0]
    latest_body = body if latest["id"] == entry["id"] else await file_text(client, prefix, latest["path"], head)
    files = {
        entry["path"]: body,
        "results/index.json": json.dumps({"version": 1, "entries": entries}, ensure_ascii=False, indent=2) + "\n",
        "results/README.md": index_markdown(entries),
        "results/LATEST.md": latest_markdown(entries, latest_body),
    }
    tree = await request(client, "POST", f"{prefix}/git/trees", json={
        "base_tree": base_tree,
        "tree": [{"path": path, "mode": "100644", "type": "blob", "content": text} for path, text in files.items()],
    })
    if tree["sha"] == base_tree:
        return {"reused": True, "path": entry["path"]}
    created = await request(client, "POST", f"{prefix}/git/commits", json={
        "message": f"Archive ScholarRadar {entry['kind']} {entry['date']}",
        "tree": tree["sha"], "parents": [head],
    })
    await request(client, "PATCH", f"{prefix}/git/refs/heads/{quote(branch, safe='/')}",
                  json={"sha": created["sha"], "force": False})
    return {"commit": created["sha"], "path": entry["path"]}


async def sync(run, payload):
    cfg = configuration()
    if not cfg.get("enabled"):
        return {"disabled": True}
    if destination(cfg) != {k: payload.get(k, "") for k in ("repository", "branch")}:
        raise ValueError("结果仓库配置已改变，请运行 github-sync 为当前目标重新排队")
    token = os.environ.get(cfg.get("token_env", "SCHOLARRADAR_GITHUB_TOKEN"), "").strip()
    if not token:
        raise ValueError("未设置 GitHub 结果仓库令牌环境变量")
    entry, body = saved_result(payload)
    async with httpx.AsyncClient(base_url="https://api.github.com", timeout=45,
                                 proxy=cfg.get("proxy"), headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ScholarRadar-Results",
    }) as client:
        return await commit_result(client, cfg, entry, body)
