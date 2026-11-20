import json
import re
from datetime import datetime
from html import unescape
from pathlib import Path
from .db import key
from .settings import deployment, now


def metadata(page):
    base = deployment().get("web_snapshot_root")
    raw = (page.get("resource") or {}).get("raw_path")
    if not base or not raw:
        return None, None, None
    path = Path(raw).resolve()
    if (
        not path.is_relative_to(Path(base).resolve())
        or path.suffix != ".html"
        or not path.is_file()
    ):
        return None, None, None
    text = path.read_text(errors="replace")

    def objects(node):
        if isinstance(node, dict):
            if node.get("@type") == "JobPosting":
                yield node
            yield from objects(node.get("@graph", []))
        if isinstance(node, list):
            for child in node:
                yield from objects(child)

    for raw_json in re.findall(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        text,
        re.I | re.S,
    ):
        try:
            data = json.loads(raw_json)
        except ValueError:
            continue
        for obj in objects(data):
            identity = obj.get("identifier")
            if isinstance(identity, dict):
                identity = identity.get("value")
            return (str(identity) if identity else None), obj.get("datePosted"), path
    plain = " ".join(unescape(re.sub(r"<[^>]*>", " ", text)).split())
    match = re.search(r"Date Posted:\s*([A-Za-z]+ \d{1,2}, \d{4})", plain, re.I)
    if match:
        try:
            return (
                None,
                datetime.strptime(match[1], "%B %d, %Y").date().isoformat(),
                path,
            )
        except ValueError:
            pass
    return None, None, path


def identify(db, org, url, title, external, published):
    by_url = db.execute(
        "SELECT posting_id FROM posting_urls WHERE url=?", (url,)
    ).fetchone()
    by_id = (
        db.execute(
            "SELECT id FROM postings WHERE organization_id=? AND official_id=?",
            (org, external),
        ).fetchone()
        if org and external
        else None
    )
    if by_url and by_id and by_url[0] != by_id[0]:
        raise ValueError("官方岗位身份冲突，需要核对")
    pid = (
        by_id
        or by_url
        or [
            key("official-id", org, external)
            if org and external
            else key("official", url)
        ]
    )[0]
    db.execute(
        "INSERT OR IGNORE INTO postings VALUES(?,?,?,?,?,?,?)",
        (pid, org, external, url, title, now(), published),
    )
    db.execute(
        "UPDATE postings SET official_id=coalesce(official_id,?),published_at=coalesce(published_at,?) WHERE id=?",
        (external, published, pid),
    )
    db.execute("INSERT OR IGNORE INTO posting_urls VALUES(?,?)", (url, pid))
    return pid
