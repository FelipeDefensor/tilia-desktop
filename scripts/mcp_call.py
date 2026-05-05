"""One-shot MCP client: issue a single tool call or read a single resource.

Usage:
    python scripts/mcp_call.py tool <name> '<json-args>'
    python scripts/mcp_call.py resource <uri>

Connects to the streamable-HTTP MCP server at MCP_URL (default
http://127.0.0.1:8765/mcp) and prints the result.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


URL = os.environ.get("MCP_URL", "http://127.0.0.1:8765/mcp")


async def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)

    kind = sys.argv[1]

    async with streamablehttp_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if kind == "tool":
                name = sys.argv[2]
                args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
                result = await session.call_tool(name, args)
                if getattr(result, "structuredContent", None):
                    print(json.dumps(result.structuredContent, indent=2))
                else:
                    for block in result.content:
                        text = getattr(block, "text", None)
                        if text is not None:
                            print(text)
            elif kind == "resource":
                uri = sys.argv[2]
                result = await session.read_resource(uri)
                print(result.contents[0].text)  # type: ignore[union-attr]
            else:
                print(f"unknown kind: {kind}")
                sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
