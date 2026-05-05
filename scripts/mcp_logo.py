"""Draw the Claude/Anthropic asterisk on TiLiA's timeline canvas via MCP.

Each row of the logo is a hierarchy timeline, each column a hierarchy
component spanning `duration/COLS` seconds. Lit cells get the brand colour;
dark cells get the dark background colour. Run against a server started
with `tilia --mcp-server`:

    python scripts/mcp_logo.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


URL = os.environ.get("MCP_URL", "http://127.0.0.1:8765/mcp")

# 17-row x 17-col 8-pointed asterisk. 1 = lit (brand), 0 = dim.
PIXELS = [
    "..........X..........",
    "..........X..........",
    ".X........X........X.",
    "..X.......X.......X..",
    "...X......X......X...",
    "....X.....X.....X....",
    ".....X....X....X.....",
    "......X...X...X......",
    ".......X..X..X.......",
    "........X.X.X........",
    "XXXXXXXXXXXXXXXXXXXXX",
    "........X.X.X........",
    ".......X..X..X.......",
    "......X...X...X......",
    ".....X....X....X.....",
    "....X.....X.....X....",
    "...X......X......X...",
    "..X.......X.......X..",
    ".X........X........X.",
    "..........X..........",
    "..........X..........",
]

DURATION = 120.0
LIT = "#cc785c"   # Anthropic peach
DIM = "#1a1a1a"   # near-black, blends into dark theme
ROW_HEIGHT = 24


async def call(s: ClientSession, name: str, args: dict | None = None) -> dict:
    res = await s.call_tool(name, args or {})
    if getattr(res, "structuredContent", None):
        return res.structuredContent
    text = res.content[0].text if res.content else "{}"
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


async def main() -> None:
    rows = len(PIXELS)
    cols = len(PIXELS[0])
    cell = DURATION / cols

    print(f"Drawing {rows}x{cols} logo over {DURATION}s (cell={cell:.4f}s)")

    async with streamablehttp_client(URL) as (rd, wr, _):
        async with ClientSession(rd, wr) as s:
            await s.initialize()

            # Window large enough to fit it.
            await call(s, "resize_window", {"width": 1500, "height": rows * ROW_HEIGHT + 200})

            # Set duration BEFORE creating non-slider timelines (avoids the
            # set_duration-after-empty-timeline hang).
            await call(s, "clear_all_timelines")
            await call(s, "set_duration", {"seconds": DURATION})

            timeline_ids: list[str] = []
            for r in range(rows):
                tl = await call(
                    s, "create_timeline",
                    {"kind": "hierarchy", "name": f"r{r:02d}"},
                )
                tid = tl["id"]
                timeline_ids.append(tid)
                await call(
                    s, "set_timeline_data",
                    {"timeline_id": tid, "attr": "height", "value": ROW_HEIGHT},
                )
                # Wipe the auto-created blank hierarchy so we can paint cells freely.
                comps = await call(s, "get_components", {"timeline_id": tid})
                for c in (comps.get("result", comps) if isinstance(comps, dict) else comps):
                    await call(
                        s, "delete_component",
                        {"timeline_id": tid, "component_id": c["id"]},
                    )

            for r, row in enumerate(PIXELS):
                tid = timeline_ids[r]
                # One hierarchy per run of identical pixels, all at level 1.
                run_start = 0
                run_lit = row[0] == "X"
                for x in range(1, cols + 1):
                    is_lit = x < cols and row[x] == "X"
                    if x == cols or is_lit != run_lit:
                        await call(
                            s, "create_hierarchy",
                            {
                                "timeline_id": tid,
                                "start": run_start * cell,
                                "end": x * cell,
                                "level": 1,
                                "color": LIT if run_lit else DIM,
                            },
                        )
                        run_start = x
                        run_lit = is_lit

            await call(s, "fit_to_duration", {})
            await call(s, "flush_paint", {})

            shot = await call(s, "screenshot", {"target": "timelines"})
            print(f"\nlogo screenshot: {shot.get('path')}")


if __name__ == "__main__":
    asyncio.run(main())
