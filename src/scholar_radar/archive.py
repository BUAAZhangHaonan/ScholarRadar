import asyncio
import json
import os
import re
import shlex
import sqlite3
import subprocess
from pathlib import Path, PurePosixPath

import asyncpg

from .db import database, key, rows
from .settings import PRIVATE, ROOT, VAR, atomic_text, deployment, now


class ArchiveUnavailable(RuntimeError):
    pass


def remote_command(relative, operation):
    cfg = deployment()["nas"]
    rel = PurePosixPath(relative)
    if (
        rel.is_absolute()
        or ".." in rel.parts
        or not rel.parts
        or rel.parts[0] not in {"documents", "papers", "reports", "backups", "sources"}
    ):
        raise ValueError("归档路径超出项目目录")
    root = PurePosixPath(cfg["root"])
    volume = PurePosixPath("/", *root.parts[1:2])
    if not re.fullmatch(r"/volume[0-9]+", str(volume)) or root.name != "ScholarRadar":
        raise ValueError("NAS 专属目录配置无效")
    quote = shlex.quote
    base = quote(str(root))
    target = quote(str(root / rel))
    parent = quote(str((root / rel).parent))
    header = (
        f"set -eu; test -d {base}; test ! -L {base}; "
        f'test "$(cd {base} && pwd -P)" = {base}; '
        f"df -P {base} | tail -1 | awk '{{print $NF}}' | grep -Eq '^{volume}(/|$)'; "
    )
    if operation == "put":
        command = header + (
            f'mkdir -p {parent}; test "$(cd {parent} && pwd -P)" = {parent}; '
            f"tmp=$(mktemp {parent}/.radar-XXXXXXXX); trap 'rm -f -- \"$tmp\"' EXIT; "
            f'cat > "$tmp"; chmod 600 "$tmp"; mv -f -- "$tmp" {target}'
        )
    elif operation == "get":
        command = header + f"test ! -L {target}; cat -- {target}"
    else:
        raise ValueError(operation)
    return [
        "sshpass",
        "-f",
        str(PRIVATE / "nas.password"),
        "ssh",
        "-T",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UpdateHostKeys=no",
        "-o",
        "ConnectTimeout=7",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "PreferredAuthentications=keyboard-interactive,password",
        cfg["user"] + "@" + cfg["host"],
        command,
    ]


def put_file(path, relative):
    path = Path(path)
    aid = key("archive", relative)
    with database(write=True) as db:
        r = db.execute("SELECT status FROM archives WHERE id=?", (aid,)).fetchone()
        if r and r[0] == "archived":
            return
        db.execute(
            "INSERT OR IGNORE INTO archives VALUES(?,?,?,'pending',NULL,NULL)",
            (aid, str(path), relative),
        )
    try:
        with path.open("rb") as data:
            result = subprocess.run(
                remote_command(relative, "put"),
                stdin=data,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=270,
            )
        if result.returncode:
            raise ArchiveUnavailable("NAS 身份、卷或写入检查失败，保留本地对象")
    except (OSError, subprocess.SubprocessError, ArchiveUnavailable) as exc:
        with database(write=True) as db:
            db.execute(
                "UPDATE archives SET status='pending',error=? WHERE id=?",
                (str(exc)[:200], aid),
            )
        raise
    with database(write=True) as db:
        db.execute(
            "UPDATE archives SET status='archived',error=NULL,archived_at=? WHERE id=?",
            (now(), aid),
        )


def backup(stamp):
    file = VAR / "backups" / (stamp + ".sqlite")
    file.parent.mkdir(parents=True, exist_ok=True)
    if not file.exists():
        temp = file.with_suffix(".incomplete")
        with database() as source:
            target = sqlite3.connect(temp)
            try:
                source.backup(target)
            finally:
                target.close()
        os.replace(temp, file)
    rel = "backups/" + file.name
    put_file(file, rel)
    return rel


def restore_copy(relative, target):
    target = Path(target).resolve()
    if (
        not target.is_relative_to(ROOT)
        or target.exists()
        or not relative.startswith("backups/")
    ):
        raise ValueError("恢复需要项目内全新的目标文件")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as output:
        result = subprocess.run(
            remote_command(relative, "get"),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.PIPE,
            timeout=240,
        )
    if result.returncode:
        target.unlink(missing_ok=True)
        raise ArchiveUnavailable("备份读取失败")
    with database(target) as db:
        if (
            db.execute("PRAGMA quick_check").fetchone()[0] != "ok"
            or db.execute("PRAGMA foreign_key_check").fetchone()
        ):
            raise ValueError("恢复库一致性校验失败")
        return {
            t: db.execute("SELECT count(*) FROM " + t).fetchone()[0]
            for t in ("works", "evidence", "claim_evidence", "jobs")
        }


async def archive_run(run):
    rid = run["id"]
    stage = VAR / "staging" / "documents"
    stage.mkdir(parents=True, exist_ok=True)
    with database() as db:
        archived = {
            row[0]
            for row in db.execute(
                "SELECT remote_path FROM archives WHERE status='archived'"
            )
        }
        docs = rows(
            db,
            "SELECT v.id,v.body,v.version,d.url,d.kind FROM revisions v JOIN documents d ON d.id=v.document_id",
        )
        raw = rows(
            db,
            "SELECT c.id,c.file FROM calls c JOIN run_calls rc ON rc.call_id=c.id WHERE rc.run_id=? AND c.file IS NOT NULL",
            (rid,),
        )
    conn = await asyncpg.connect(
        deployment()["mirror_dsn"],
        timeout=8,
        server_settings={"default_transaction_read_only": "on"},
    )
    pdfs = {}
    try:
        for d in docs:
            if d["kind"] == "paper" and d["version"] and "/abs/" in d["url"]:
                vid = d["url"].split("/abs/")[-1] + d["version"]
                if "papers/" + vid.replace("/", "_") + ".pdf" in archived:
                    continue
                local = await conn.fetchval(
                    "SELECT local_path FROM pdf_assets WHERE versioned_id=$1 AND source='remote' AND local_path IS NOT NULL LIMIT 1",
                    vid,
                )
                if local and Path(local).is_file():
                    pdfs[vid] = Path(local)
    finally:
        await conn.close()
    objects = []
    uploaded_docs = 0
    for d in docs:
        file = stage / (d["id"] + ".txt")
        rel = "documents/" + file.name
        if rel in archived:
            continue
        bound = int(deployment().get("staging_limit_bytes", 2147483648))
        size = len(d["body"].encode())
        occupied = sum(
            f.stat().st_size for f in stage.iterdir() if f.is_file() and f != file
        )
        if occupied + size > bound:
            with database(write=True) as local:
                local.execute(
                    "INSERT OR REPLACE INTO archives VALUES(?,?,?,'pending',?,NULL)",
                    (
                        key("archive", rel),
                        str(file),
                        rel,
                        "本地暂存限额，归档就绪后由固定文档修订重新生成",
                    ),
                )
            raise ArchiveUnavailable("本地暂存到达配置限额")
        atomic_text(file, d["body"])
        await asyncio.to_thread(put_file, file, rel)
        file.unlink(missing_ok=True)
        uploaded_docs += 1
    objects.extend(
        (path, "papers/" + vid.replace("/", "_") + ".pdf") for vid, path in pdfs.items()
    )
    objects.extend((Path(x["file"]), "sources/" + x["id"] + ".json") for x in raw)
    out = ROOT / "exports" / run["as_of"] / run["kind"]
    report_file = out / "internprep.json"
    edition = (
        json.loads(report_file.read_text())["snapshot_id"]
        if report_file.exists()
        else rid
    )
    objects.extend(
        (
            p,
            "reports/"
            + run["as_of"]
            + "/"
            + run["kind"]
            + "/"
            + edition
            + "/"
            + p.name,
        )
        for p in out.glob("*")
        if p.is_file()
    )
    for path, rel in objects:
        await asyncio.to_thread(put_file, path, rel)
        if path.parent == stage:
            path.unlink(missing_ok=True)
    snap = await asyncio.to_thread(backup, edition)
    keep = int(deployment().get("local_backup_count", 7))
    with database() as db:
        retained = {
            a[0]
            for a in db.execute(
                "SELECT local_path FROM archives WHERE remote_path LIKE 'backups/%' AND status='archived'"
            )
        }
    backups = sorted(
        (VAR / "backups").glob("*.sqlite"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for historic in backups[max(1, keep) :]:
        if str(historic) in retained:
            historic.unlink(missing_ok=True)
    return {"objects": len(objects) + uploaded_docs, "pdfs": len(pdfs), "backup": snap}
