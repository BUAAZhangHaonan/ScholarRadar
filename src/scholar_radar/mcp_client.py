"""Live MCP discovery and calls through the official SDK."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
import jsonschema
from mcp import ClientSession
from mcp.client.sse import sse_client

from .settings import ROOT, atomic_text, deployment, now


@asynccontextmanager
async def session(name):
    cfg = deployment()["services"][name]
    if cfg["type"] != "sse":
        raise ValueError(f"未配置的 transport: {cfg['type']}")
    def client(**kwargs):
        return httpx.AsyncClient(**kwargs, trust_env=False)
    async with sse_client(cfg["url"], headers=cfg["headers"], timeout=20, sse_read_timeout=2400,
                          httpx_client_factory=client) as streams:
        async with ClientSession(*streams) as active:
            init = await active.initialize()
            yield active, init


async def capabilities(name):
    async with session(name) as (active, init):
        cursor, tools = None, []
        while True:
            result = await active.list_tools(cursor=cursor)
            tools.extend(t.model_dump(by_alias=True, exclude_none=True) for t in result.tools)
            cursor = result.nextCursor
            if not cursor:
                break
        return {"transport": "sse", "version": init.serverInfo.version,
                "protocol": init.protocolVersion, "tools": tools}


async def inventory():
    names = list(deployment()["services"])
    items = await asyncio.gather(*(capabilities(name) for name in names), return_exceptions=True)
    services = {name: ({"status":"unavailable","error_type":type(item).__name__}
                       if isinstance(item, BaseException) else {"status":"ok", **item})
                for name, item in zip(names, items)}
    result = {"observed_at": now(), "services": services}
    atomic_text(ROOT / "var/capabilities.json", json.dumps(result, ensure_ascii=False, indent=2))
    return result


async def call(name, tool, args):
    catalog = json.loads((ROOT / "var/capabilities.json").read_text())
    contract = next((t for t in catalog["services"][name].get("tools",[]) if t["name"] == tool), None)
    if contract is None:
        raise ValueError(f"{name}/{tool} 未在能力目录中返回")
    jsonschema.validate(args, contract["inputSchema"])
    async with session(name) as (active, _):
        result = await active.call_tool(tool, args, read_timeout_seconds=timedelta(minutes=38))
    if result.isError:
        raise RuntimeError(f"{name}/{tool} 返回协议或工具错误")
    data = result.structuredContent
    if data is None:
        blocks = [x.text for x in result.content if x.type == "text"]
        if not blocks:
            raise ValueError("MCP 返回缺少文本或结构化数据")
        data = json.loads(blocks[0]) if len(blocks)==1 else [json.loads(x) for x in blocks]
    if isinstance(data, dict) and set(data)=={"result"}:
        data = data["result"]
    if isinstance(data, str):
        data = json.loads(data)
    return data


if __name__ == "__main__":
    result = asyncio.run(inventory())
    for name, item in result["services"].items():
        print(name, item["status"], [tool["name"] for tool in item.get("tools", [])])
