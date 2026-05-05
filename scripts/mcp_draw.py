"""Paint a pixel-art pattern onto the grid set up by `mcp_grid.py`.

Pattern file is JSON with these fields:

    {
      "pattern": ["XX.XX", "X.X.X", ".XXX.", "X.X.X", "XX.XX"],
      "palette": {"X": "#cc785c", ".": null},
      "row_offset": 0,           // optional, default 0
      "col_offset": 0            // optional, default 0
    }

Each char in `pattern` maps to a colour via `palette`. `null` (or a
missing entry) means "leave the cell untouched" — useful for drawing
sparse images on top of an existing canvas.

Usage:
    python scripts/mcp_draw.py pattern.json
    python scripts/mcp_draw.py pattern.json --no-clear
    python scripts/mcp_draw.py pattern.json --row 30 --col 40
    python scripts/mcp_draw.py --clear-only

Run against a server started with `tilia --mcp-server`, after the grid
has been set up by `mcp_grid.py`.
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


async def get_row_timelines(s: ClientSession) -> tuple[list[str], float, int]:
    """Return (timeline_ids in row order, duration, grid_size)."""
    tls_raw = await call(s, "list_timelines")
    tls = tls_raw.get("result", tls_raw) if isinstance(tls_raw, dict) else tls_raw
    rows = sorted(
        (t for t in tls if t["kind"] == "HIERARCHY_TIMELINE" and t["name"].startswith("r")),
        key=lambda t: t["name"],
    )
    if not rows:
        raise RuntimeError("No hierarchy rows found. Run mcp_grid.py first.")

    dur_res = await s.read_resource("tilia://media/duration")
    duration = json.loads(dur_res.contents[0].text)["duration"]  # type: ignore[union-attr]
    if not duration:
        raise RuntimeError("Media duration is 0; run mcp_grid.py to set duration first.")
    return [r["id"] for r in rows], float(duration), len(rows)


async def clear_all_cells(s: ClientSession, timeline_ids: list[str]) -> None:
    print(f"Clearing {len(timeline_ids)} rows...")
    for i, tid in enumerate(timeline_ids):
        comps_raw = await call(s, "get_components", {"timeline_id": tid})
        items = comps_raw.get("result", comps_raw) if isinstance(comps_raw, dict) else comps_raw
        for c in items if isinstance(items, list) else []:
            await call(
                s, "delete_component",
                {"timeline_id": tid, "component_id": c["id"]},
            )
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(timeline_ids)} cleared")


async def paint_pattern(
    s: ClientSession,
    timeline_ids: list[str],
    duration: float,
    grid_size: int,
    pattern: list[str],
    palette: dict[str, str | None],
    row_offset: int,
    col_offset: int,
) -> int:
    cell = duration / grid_size
    painted = 0

    for r, row_str in enumerate(pattern):
        target_row = r + row_offset
        if target_row < 0 or target_row >= grid_size:
            continue
        tid = timeline_ids[target_row]

        # Coalesce runs of identical chars whose palette entry is non-null.
        x = 0
        n = len(row_str)
        while x < n:
            ch = row_str[x]
            colour = palette.get(ch)
            if colour is None:
                x += 1
                continue
            run_end = x + 1
            while run_end < n and row_str[run_end] == ch:
                run_end += 1

            start_col = x + col_offset
            end_col = run_end + col_offset
            if end_col <= 0 or start_col >= grid_size:
                x = run_end
                continue
            start_col = max(start_col, 0)
            end_col = min(end_col, grid_size)

            await call(
                s, "create_hierarchy",
                {
                    "timeline_id": tid,
                    "start": start_col * cell,
                    "end": end_col * cell,
                    "level": 1,
                    "color": colour,
                },
            )
            painted += 1
            x = run_end

    return painted


async def run(pattern_file: str | None, clear: bool, row: int | None, col: int | None) -> None:
    spec: dict = {}
    if pattern_file:
        with open(pattern_file) as f:
            spec = json.load(f)

    pattern = spec.get("pattern", [])
    palette = spec.get("palette", {})
    row_offset = row if row is not None else int(spec.get("row_offset", 0))
    col_offset = col if col is not None else int(spec.get("col_offset", 0))

    async with streamablehttp_client(URL) as (rd, wr, _):
        async with ClientSession(rd, wr) as s:
            await s.initialize()

            timeline_ids, duration, size = await get_row_timelines(s)
            print(f"Grid: {size}x{size}, duration={duration}s")

            if clear:
                await clear_all_cells(s, timeline_ids)

            if pattern:
                painted = await paint_pattern(
                    s, timeline_ids, duration, size,
                    pattern, palette, row_offset, col_offset,
                )
                print(f"Painted {painted} hierarchy components.")

            await call(s, "flush_paint", {})


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("pattern_file", nargs="?", help="JSON file with pattern + palette")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--no-clear", dest="clear", action="store_false",
                     help="Don't wipe existing cells before painting (compose on top)")
    grp.add_argument("--clear-only", action="store_true",
                     help="Wipe all cells and exit without drawing")
    p.set_defaults(clear=True)
    p.add_argument("--row", type=int, help="Row offset (overrides pattern file)")
    p.add_argument("--col", type=int, help="Column offset (overrides pattern file)")
    args = p.parse_args()

    if args.clear_only:
        asyncio.run(run(None, clear=True, row=None, col=None))
    else:
        if not args.pattern_file:
            p.error("pattern_file is required unless --clear-only is given")
        asyncio.run(run(args.pattern_file, args.clear, args.row, args.col))


if __name__ == "__main__":
    main()
