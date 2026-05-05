"""Reproducer for the set-duration hang found via MCP bug hunt.

Ground truth, run repeatedly: TiLiA freezes when `set_duration` is called
with a non-zero value while a non-slider timeline already exists and the
current duration is zero.

Each step uses a 5s timeout. If a step exceeds the timeout, we report
the hang and exit. The TiLiA process needs to be restarted afterwards.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


URL = os.environ.get("MCP_URL", "http://127.0.0.1:8765/mcp")


async def call(s: ClientSession, name: str, args: dict | None = None) -> dict:
    res = await s.call_tool(name, args or {})
    if getattr(res, "structuredContent", None):
        return res.structuredContent
    text = res.content[0].text if res.content else "{}"
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


async def step(label: str, coro, timeout: float = 5.0) -> object:
    print(f"  -> {label} ... ", end="", flush=True)
    try:
        out = await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        print(f"HUNG after {timeout}s")
        sys.exit(2)
    print("ok")
    return out


async def main() -> None:
    print("Repro: set_duration to non-zero hangs when marker timeline exists at duration=0")
    async with streamablehttp_client(URL) as (rd, wr, _):
        async with ClientSession(rd, wr) as s:
            await s.initialize()
            await step("clear", call(s, "clear_all_timelines"))
            await step("create marker timeline (duration=0)", call(s, "create_timeline", {"kind": "marker", "name": "M"}))
            await step("set_duration to 60 — expected HANG", call(s, "set_duration", {"seconds": 60}), timeout=5)
            print("did not hang this time — try the other ordering")


if __name__ == "__main__":
    asyncio.run(main())
