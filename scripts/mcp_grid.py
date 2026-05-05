"""Set up an N×N empty grid of hierarchy timelines for pixel-art drawing.

Each row is a hierarchy timeline of `row_height` px; each cell spans
`duration / size` seconds. After setup, every row is empty (no
hierarchies), ready to be painted by `scripts/mcp_draw.py` or any
client that calls `create_hierarchy`.

Usage:
    python scripts/mcp_grid.py [--size 100] [--duration 100] [--row-height 10]

Run against a server started with `tilia --mcp-server`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

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


async def setup(size: int, duration: float, row_height: int) -> None:
    cell_w = duration / size

    async with streamablehttp_client(URL) as (rd, wr, _):
        async with ClientSession(rd, wr) as s:
            await s.initialize()

            # Window tall enough for all rows + toolbar + status bar.
            await call(
                s, "resize_window",
                {"width": 1500, "height": size * row_height + 200},
            )

            # Safe order to dodge the set_duration-on-empty-tl hang:
            # clear → set_duration (while only slider exists) → create rows.
            await call(s, "clear_all_timelines")
            await call(s, "set_duration", {"seconds": duration})

            print(f"Creating {size} hierarchy rows...")
            for r in range(size):
                tl = await call(
                    s, "create_timeline",
                    {"kind": "hierarchy", "name": f"r{r:03d}"},
                )
                tid = tl.get("id") or tl.get("result", {}).get("id")
                if tid is None:
                    raise RuntimeError(f"create_timeline returned: {tl}")

                await call(
                    s, "set_timeline_data",
                    {"timeline_id": tid, "attr": "height", "value": row_height},
                )
                # Wipe the auto-created blank hierarchy so painting starts clean.
                comps = await call(s, "get_components", {"timeline_id": tid})
                items = comps.get("result", comps) if isinstance(comps, dict) else comps
                for c in items if isinstance(items, list) else []:
                    await call(
                        s, "delete_component",
                        {"timeline_id": tid, "component_id": c["id"]},
                    )
                if (r + 1) % 10 == 0:
                    print(f"  {r + 1}/{size} rows ready")

            await call(s, "fit_to_duration", {})
            await call(s, "flush_paint", {})

            print(
                f"\nGrid ready: {size}x{size}, "
                f"cell={cell_w:.4f}s, row_height={row_height}px"
            )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--size", type=int, default=100)
    p.add_argument("--duration", type=float, default=100.0)
    p.add_argument("--row-height", type=int, default=10)
    args = p.parse_args()
    asyncio.run(setup(args.size, args.duration, args.row_height))


if __name__ == "__main__":
    main()
