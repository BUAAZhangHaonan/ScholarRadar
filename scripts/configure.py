"""Create the local deployment configuration from existing service settings."""

import argparse
import getpass
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
from scholar_radar.db import database, migrate
from scholar_radar.profile import save
from scholar_radar.settings import PRIVATE, atomic_text, dump


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mcp-client", type=Path, required=True)
    p.add_argument("--trace-name", default="scholartrace")
    p.add_argument("--analysis-name", default="scholaranalysis")
    p.add_argument("--web-name", default="webresearch-mcp")
    p.add_argument("--analysis-env", type=Path, required=True)
    p.add_argument("--mirror-env", type=Path, required=True)
    p.add_argument("--trace-env", type=Path)
    p.add_argument("--web-data-root", type=Path)
    p.add_argument("--bind", required=True)
    p.add_argument("--port", type=int, default=8769)
    p.add_argument("--nas-host", required=True)
    p.add_argument("--nas-user", required=True)
    p.add_argument("--nas-root", required=True)
    p.add_argument("--profile", type=Path, required=True)
    args = p.parse_args()
    os.umask(0o077)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    target = PRIVATE / "deployment.json"
    if target.exists():
        p.error("本机已有部署配置。调整既有私有配置后重启服务。")
    clients = json.loads(args.mcp_client.read_text())["mcpServers"]
    names = {
        "trace": args.trace_name,
        "analysis": args.analysis_name,
        "web": args.web_name,
    }
    services = {}
    for name, alias in names.items():
        cfg = clients[alias]
        if cfg["type"] != "sse" or urlsplit(cfg["url"]).scheme not in {"http", "https"}:
            p.error("需要当前三个 MCP 的 SSE 配置")
        services[name] = {k: cfg[k] for k in ("type", "url", "headers") if k in cfg}
    analysis = dotenv_values(args.analysis_env)
    mirror = dotenv_values(args.mirror_env)
    profile = json.loads(args.profile.read_text())
    secret = getpass.getpass("NAS SSH 密码：")
    if not secret:
        p.error("NAS 密码为空")
    config = {
        "services": services,
        "model_base": analysis["SCHOLAR_ANALYSIS_DEEPSEEK_BASE_URL"],
        "model_key": analysis["SCHOLAR_ANALYSIS_DEEPSEEK_API_KEY"],
        "site_token": secrets.token_urlsafe(36),
        "mirror_dsn": mirror["ARXIV_MIRROR_DATABASE_URL"].replace(
            "postgresql+asyncpg:", "postgresql:"
        ),
        "s2_key": dotenv_values(args.trace_env).get(
            "SCHOLARTRACE_SEMANTIC_SCHOLAR_API_KEY", ""
        )
        if args.trace_env
        else "",
        "bind_host": args.bind,
        "port": args.port,
        "nas": {"host": args.nas_host, "user": args.nas_user, "root": args.nas_root},
    }
    if args.web_data_root:
        config["web_snapshot_root"] = str(args.web_data_root.resolve())
    migrate()
    with database(write=True) as db:
        save(db, profile)
    atomic_text(PRIVATE / "nas.password", secret + "\n")
    atomic_text(target, dump(config))
    print("本地配置和画像已创建。")


if __name__ == "__main__":
    main()
