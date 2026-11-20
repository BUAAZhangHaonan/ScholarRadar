import argparse
import asyncio
import json
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo


def main():
    parser = argparse.ArgumentParser(
        prog="scholar-radar", description="ScholarRadar 研究工作台"
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("init", "serve", "inventory", "login-link", "status"):
        sub.add_parser(name)
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("kind", choices=["daily", "weekly", "monthly"])
    run.add_argument("--day", type=date.fromisoformat)
    b = sub.add_parser("backup")
    b.add_argument("name")
    r = sub.add_parser("restore-copy")
    r.add_argument("relative")
    r.add_argument("target", type=Path)
    a = parser.parse_args()
    from .db import database, migrate
    from .settings import deployment

    migrate()
    if a.cmd == "init":
        from .registry import initialize

        with database(write=True) as db:
            initialize(db)
    elif a.cmd == "serve":
        import uvicorn

        cfg = deployment()
        uvicorn.run(
            "scholar_radar.api:app",
            host=cfg["bind_host"],
            port=cfg["port"],
            access_log=False,
        )
    elif a.cmd == "inventory":
        from .mcp_client import inventory

        catalog = asyncio.run(inventory())
        print({s: i["status"] for s, i in catalog["services"].items()})
    elif a.cmd == "worker":
        from .worker import worker

        asyncio.run(worker(a.once))
    elif a.cmd == "run":
        from .profile import get_profile
        from .queue import enqueue

        with database(write=True) as db:
            day = a.day or datetime.now(ZoneInfo(get_profile(db)["timezone"])).date()
            print(enqueue(db, a.kind, day))
    elif a.cmd == "login-link":
        from .access import issue_link

        print(issue_link())
    elif a.cmd == "backup":
        from .archive import backup
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", a.name):
            parser.error("备份名称无效")
        print(backup(a.name))
    elif a.cmd == "restore-copy":
        from .archive import restore_copy

        print(restore_copy(a.relative, a.target))
    else:
        from .operations_api import status

        print(json.dumps(status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
