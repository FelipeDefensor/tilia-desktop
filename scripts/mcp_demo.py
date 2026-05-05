"""Demo client: drives a running TiLiA via its MCP server.

Run:
    # Terminal 1
    tilia --mcp-server

    # Terminal 2
    python scripts/mcp_demo.py

The demo:
  1. Connects over streamable HTTP and lists exposed tools/resources.
  2. Sets a media duration (skips the "no media" prompt).
  3. Adds a marker timeline named "Demo".
  4. Adds a few markers at fixed times.
  5. Reads tilia://state and prints a one-line summary per timeline.
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main(url: str) -> None:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("tools:")
            for t in tools.tools:
                print(f"  - {t.name}: {t.description.splitlines()[0] if t.description else ''}")

            resources = await session.list_resources()
            print("resources:")
            for r in resources.resources:
                print(f"  - {r.uri}: {r.description or ''}")

            print("\n-- driving the app --")
            await _call(session, "set_duration", {"seconds": 60.0})
            await _call(session, "add_timeline", {"kind": "marker", "name": "Demo"})
            for t in (5.0, 10.0, 15.0, 30.0):
                await _call(session, "add_marker", {"time": t})

            print("\n-- tilia://state --")
            res = await session.read_resource("tilia://state")
            payload = res.contents[0].text  # type: ignore[union-attr]
            state = json.loads(payload)
            for tid, tl in state.get("timelines", {}).items():
                kind = tl.get("kind", "?")
                name = tl.get("name", "")
                comps = tl.get("components", {})
                count = len(comps if isinstance(comps, dict) else [])
                print(f"  [{tid}] kind={kind} name={name!r} components={count}")


async def _call(session: ClientSession, name: str, args: dict) -> None:
    result = await session.call_tool(name, args)
    text = result.content[0].text if result.content else ""
    print(f"  {name}({args}) -> {text}")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/mcp"
    asyncio.run(main(url))
