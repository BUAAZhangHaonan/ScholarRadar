"""Verify concrete repository files on the host that publishes them."""

import ssl
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit
import httpx
from .changes import invalidate
from .db import key
from .evidence import revision, span
from .settings import now

CODE = {".py", ".rs", ".cpp", ".c", ".cu", ".jl", ".ipynb"}
WEIGHTS = {".safetensors", ".gguf", ".onnx", ".pt", ".pth"}
DATA = {".parquet", ".jsonl", ".arrow", ".csv", ".tsv"}


def artifact_kind(path):
    parts = PurePosixPath(path).parts
    if any(x.startswith(".") for x in parts) or any(
        x.lower() in {"test", "tests", "examples", "docs"} for x in parts[:-1]
    ):
        return None
    ext = PurePosixPath(path).suffix.lower()
    return (
        "code"
        if ext in CODE
        else "weights"
        if ext in WEIGHTS
        else "data"
        if ext in DATA
        else None
    )


async def available_file(client, url, *, github_blob=False):
    headers = {"Range": "bytes=0-255"}
    if github_blob:
        headers["Accept"] = "application/vnd.github.raw+json"
    try:
        async with client.stream("GET", url, headers=headers) as response:
            return await file_signature(response, github_blob)
    except httpx.TransportError:
        return None


async def file_signature(response, github_blob):
    if github_blob and response.headers.get("content-type", "").startswith(
        "application/json"
    ):
        return None
    if response.status_code not in (200, 206):
        return None
    if "text/html" in response.headers.get("content-type", "").lower():
        return None
    prefix = await anext(response.aiter_bytes(chunk_size=256), b"")
    signature = prefix.lstrip().lower()
    if not signature or signature.startswith(
        (b"version https://git-lfs.github.com/spec/", b"<!doctype html", b"<html")
    ):
        return None
    return response.headers.get("etag") or True


async def files_at(url):
    parsed = urlsplit(url)
    parts = parsed.path.strip("/").split("/")
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return []
    async with httpx.AsyncClient(
        verify=ssl.create_default_context(),
        timeout=18,
        follow_redirects=True,
        headers={"User-Agent": "ScholarRadar research resource verification"},
    ) as client:
        if parsed.hostname == "github.com" and len(parts) == 2:
            name = "/".join(quote(x, safe="") for x in parts)
            base = f"https://api.github.com/repos/{name}"
            info = await client.get(base)
            info.raise_for_status()
            branch = info.json()["default_branch"]
            head = await client.get(base + "/commits/" + quote(branch, safe=""))
            head.raise_for_status()
            commit = head.json()["sha"]
            tree = head.json()["commit"]["tree"]["sha"]
            req = await client.get(base + "/git/trees/" + tree, params={"recursive": 1})
            req.raise_for_status()
            found = {}
            probes = {}
            for f in req.json().get("tree", []):
                kind = artifact_kind(f["path"])
                if (
                    f.get("type") != "blob"
                    or not kind
                    or kind in found
                    or not f.get("size")
                ):
                    continue
                if kind in {"weights", "data"}:
                    if probes.get(kind, 0) >= 3:
                        continue
                    probes[kind] = probes.get(kind, 0) + 1
                    if not await available_file(
                        client, base + "/git/blobs/" + f["sha"], github_blob=True
                    ):
                        continue
                found[kind] = {
                    "kind": kind,
                    "path": f["path"],
                    "version": f["sha"],
                    "url": "https://github.com/"
                    + name
                    + "/blob/"
                    + commit
                    + "/"
                    + quote(f["path"]),
                    "source_url": str(req.url),
                    "raw": req.text,
                    "locator": f["sha"],
                    "source_version": tree,
                }
            return list(found.values())
        if parsed.hostname == "huggingface.co" and len(parts) in (2, 3):
            dataset = parts[0] == "datasets"
            names = parts[1:] if dataset else parts
            if len(names) != 2:
                return []
            name = "/".join(quote(x, safe="") for x in names)
            meta = await client.get(
                "https://huggingface.co/api/"
                + ("datasets/" if dataset else "models/")
                + name
            )
            meta.raise_for_status()
            obj = meta.json()
            if obj.get("gated") or obj.get("private") or not obj.get("sha"):
                return []
            found = {}
            for f in obj.get("siblings", []):
                path = f.get("rfilename", "")
                kind = artifact_kind(path)
                if not kind or kind in found:
                    continue
                location = (
                    "https://huggingface.co/"
                    + ("datasets/" if dataset else "")
                    + name
                    + "/resolve/"
                    + obj["sha"]
                    + "/"
                    + quote(path)
                )
                available = await available_file(client, location)
                if not available:
                    continue
                version = available if isinstance(available, str) else obj["sha"]
                found[kind] = {
                    "kind": kind,
                    "path": path,
                    "version": version,
                    "url": location,
                    "source_url": str(meta.url),
                    "raw": meta.text,
                    "locator": path,
                    "source_version": obj["sha"],
                }
            return list(found.values())
    return []


def register(db, resource_id, files):
    changed = []
    for f in files:
        stamp = now()
        aid = key("verified-artifact", resource_id, f["kind"], f["path"], f["version"])
        old = db.execute(
            "SELECT id FROM verified_artifacts WHERE id=?", (aid,)
        ).fetchone()
        if old:
            db.execute(
                "UPDATE verified_artifacts SET last_verified_at=? WHERE id=?",
                (stamp, aid),
            )
            continue
        text = f["raw"]
        pos = text.find(f["locator"])
        if pos < 0:
            continue
        rid = revision(
            db,
            None,
            f["source_url"],
            "release",
            f["source_version"],
            text,
            mode="publisher_json",
        )
        a = max(0, pos - 130)
        b = min(len(text), pos + len(f["locator"]) + 80)
        eid = span(db, rid, a, b, text[a:b])
        db.execute(
            "INSERT INTO verified_artifacts VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                aid,
                resource_id,
                f["kind"],
                f["path"],
                f["version"],
                f["url"],
                f["source_url"],
                eid,
                stamp,
                stamp,
            ),
        )
        invalidate(db, "resource", resource_id, aid)
        changed.append(aid)
    return changed
