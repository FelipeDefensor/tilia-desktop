"""Systematic edge-case probing of TiLiA via MCP.

Each probe is a small async coroutine that exercises one shape of input
and asserts what should happen. Anything that prints "FOUND:" is a
potential bug worth investigating.

Run against a server started with `tilia --mcp-server`:
    python scripts/mcp_bughunt.py
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


async def read(s: ClientSession, uri: str) -> dict:
    res = await s.read_resource(uri)
    return json.loads(res.contents[0].text)  # type: ignore[union-attr]


def expect(label: str, condition: bool, detail: str = "") -> None:
    flag = "OK   " if condition else "FOUND"
    print(f"[{flag}] {label}{(' — ' + detail) if detail else ''}")


async def reset(s: ClientSession, duration: float = 60.0) -> None:
    """Get the app into a known state."""
    await call(s, "clear_all_timelines")
    await call(s, "set_duration", {"seconds": duration})


# ---------- probes ----------

async def probe_marker_outside_duration(s: ClientSession) -> None:
    print("\n--- markers outside duration ---")
    await reset(s, 30.0)
    tl = await call(s, "create_timeline", {"kind": "marker", "name": "M"})
    tid = tl["id"]
    r1 = await call(s, "create_marker", {"timeline_id": tid, "time_seconds": 100})
    r2 = await call(s, "create_marker", {"timeline_id": tid, "time_seconds": -1})
    r3 = await call(s, "create_marker", {"timeline_id": tid, "time_seconds": 0})
    expect(
        "marker at t > duration is rejected or clamped",
        r1.get("ok") is False,
        f"got {r1!r} (state: marker may exist past media end)",
    )
    expect("marker at t < 0 is rejected", r2.get("ok") is False, f"got {r2!r}")
    expect("marker at t = 0 accepted", r3.get("ok") is True, f"got {r3!r}")


async def probe_hierarchy_inverted(s: ClientSession) -> None:
    print("\n--- hierarchy with end < start ---")
    await reset(s, 60.0)
    tl = await call(s, "create_timeline", {"kind": "hierarchy", "name": "H"})
    tid = tl["id"]
    r = await call(
        s, "create_hierarchy", {"timeline_id": tid, "start": 30, "end": 10}
    )
    expect("end < start rejected", r.get("ok") is False, f"got {r!r}")


async def probe_hierarchy_zero_length(s: ClientSession) -> None:
    print("\n--- hierarchy with end == start ---")
    await reset(s, 60.0)
    tl = await call(s, "create_timeline", {"kind": "hierarchy", "name": "H"})
    tid = tl["id"]
    r = await call(
        s, "create_hierarchy", {"timeline_id": tid, "start": 30, "end": 30}
    )
    expect(
        "zero-length hierarchy: behaviour documented",
        True,
        f"result: {r!r}",
    )


async def probe_undo_overflow(s: ClientSession) -> None:
    print("\n--- undo with empty history ---")
    await reset(s, 60.0)
    r = await call(s, "execute_command", {"name": "edit.undo"})
    expect("undo with no history doesn't crash", r.get("ok") is True, f"{r!r}")
    for _ in range(50):
        r = await call(s, "execute_command", {"name": "edit.undo"})
    expect("50 undos in a row don't crash", r.get("ok") is True, f"{r!r}")


async def probe_redo_without_undo(s: ClientSession) -> None:
    print("\n--- redo with nothing to redo ---")
    await reset(s, 60.0)
    r = await call(s, "execute_command", {"name": "edit.redo"})
    expect("redo with no future doesn't crash", r.get("ok") is True, f"{r!r}")


async def probe_duplicate_marker_at_same_time(s: ClientSession) -> None:
    print("\n--- two markers at same time ---")
    await reset(s, 60.0)
    tl = await call(s, "create_timeline", {"kind": "marker", "name": "M"})
    tid = tl["id"]
    a = await call(s, "create_marker", {"timeline_id": tid, "time_seconds": 5})
    b = await call(s, "create_marker", {"timeline_id": tid, "time_seconds": 5})
    comps = await call(s, "get_components", {"timeline_id": tid})
    count = len(comps.get("result", comps) if isinstance(comps, dict) else comps)
    expect(
        "duplicate markers at same time policy",
        True,
        f"a={a.get('ok')} b={b.get('ok')} count={count}",
    )


async def probe_set_duration_zero(s: ClientSession) -> None:
    print("\n--- set duration to 0 ---")
    await reset(s, 60.0)
    r = await call(s, "set_duration", {"seconds": 0})
    state = await read(s, "tilia://state")
    expect(
        "duration = 0 doesn't crash",
        r.get("ok") is True,
        f"resulting media_length={state['media_metadata'].get('media length')}",
    )


async def probe_set_duration_negative(s: ClientSession) -> None:
    print("\n--- set duration to negative ---")
    await reset(s, 60.0)
    r = await call(s, "set_duration", {"seconds": -10})
    state = await read(s, "tilia://state")
    expect(
        "negative duration handled",
        True,
        f"r={r!r} stored={state['media_metadata'].get('media length')}",
    )


async def probe_set_duration_huge(s: ClientSession) -> None:
    print("\n--- set duration to 1e9 ---")
    await reset(s, 60.0)
    r = await call(s, "set_duration", {"seconds": 1e9})
    state = await read(s, "tilia://state")
    expect(
        "huge duration handled",
        r.get("ok") is True,
        f"r={r!r} stored={state['media_metadata'].get('media length')}",
    )


async def probe_unicode_label(s: ClientSession) -> None:
    print("\n--- unicode/special label ---")
    await reset(s, 60.0)
    tl = await call(s, "create_timeline", {"kind": "marker", "name": "M"})
    tid = tl["id"]
    text = "éñ中文 \U0001f680 ​ NULL\x00END"
    a = await call(
        s, "create_marker",
        {"timeline_id": tid, "time_seconds": 1, "label": text},
    )
    state = await read(s, "tilia://state")
    saved = None
    for tl_ in state.get("timelines", {}).values():
        if tl_.get("kind") == "MARKER_TIMELINE":
            for c in tl_.get("components", {}).values():
                saved = c.get("label")
    expect(
        "unicode and embedded NUL preserved",
        saved == text,
        f"sent={text!r} stored={saved!r}",
    )


async def probe_invalid_color(s: ClientSession) -> None:
    print("\n--- invalid hex color ---")
    await reset(s, 60.0)
    tl = await call(s, "create_timeline", {"kind": "hierarchy", "name": "H"})
    tid = tl["id"]
    r = await call(
        s, "create_hierarchy",
        {"timeline_id": tid, "start": 0, "end": 10, "color": "not-a-color"},
    )
    expect(
        "invalid color rejected",
        r.get("ok") is False,
        f"got {r!r}",
    )


async def probe_rapid_create_delete(s: ClientSession) -> None:
    print("\n--- rapid create/delete cycle (resource leak smoke) ---")
    await reset(s, 60.0)
    tl = await call(s, "create_timeline", {"kind": "marker", "name": "M"})
    tid = tl["id"]
    ids: list[str] = []
    for i in range(40):
        r = await call(
            s, "create_marker",
            {"timeline_id": tid, "time_seconds": float(i % 30)},
        )
        if r.get("ok"):
            ids.append(r["id"])
    for cid in ids:
        await call(s, "delete_component", {"timeline_id": tid, "component_id": cid})
    comps = await call(s, "get_components", {"timeline_id": tid})
    remaining = comps.get("result", comps) if isinstance(comps, dict) else comps
    expect(
        "all created markers cleaned up",
        len(remaining) == 0,
        f"{len(remaining)} left",
    )


async def probe_set_negative_height(s: ClientSession) -> None:
    print("\n--- timeline height = -1 ---")
    await reset(s, 60.0)
    tl = await call(s, "create_timeline", {"kind": "marker", "name": "M"})
    tid = tl["id"]
    r = await call(s, "set_timeline_data", {"timeline_id": tid, "attr": "height", "value": -50})
    info = await call(s, "list_timelines")
    height = None
    for t in info.get("result", info):
        if t["id"] == tid:
            height = t["height"]
    expect(
        "negative height clamped or rejected",
        height is None or height >= 0,
        f"r={r!r} stored_height={height}",
    )


async def probe_set_huge_height(s: ClientSession) -> None:
    print("\n--- timeline height = 100000 ---")
    await reset(s, 60.0)
    tl = await call(s, "create_timeline", {"kind": "marker", "name": "M"})
    tid = tl["id"]
    r = await call(s, "set_timeline_data", {"timeline_id": tid, "attr": "height", "value": 100000})
    info = await call(s, "list_timelines")
    height = None
    for t in info.get("result", info):
        if t["id"] == tid:
            height = t["height"]
    expect(
        "huge height accepted or clamped",
        True,
        f"r={r!r} stored_height={height}",
    )


async def probe_zero_duration_then_create(s: ClientSession) -> None:
    print("\n--- create marker after duration -> 0 ---")
    await reset(s, 60.0)
    tl = await call(s, "create_timeline", {"kind": "marker", "name": "M"})
    tid = tl["id"]
    await call(s, "set_duration", {"seconds": 0})
    r = await call(s, "create_marker", {"timeline_id": tid, "time_seconds": 1})
    expect(
        "marker beyond zero duration rejected",
        r.get("ok") is False,
        f"got {r!r}",
    )


async def probe_export_json_no_path(s: ClientSession) -> None:
    print("\n--- file.export.json without path ---")
    await reset(s, 60.0)
    r = await call(s, "execute_command", {"name": "file.export.json"})
    expect("export without path doesn't crash", r.get("ok") is True, f"{r!r}")


async def probe_query_unsupported_get(s: ClientSession) -> None:
    print("\n--- query unsupported Get key ---")
    r = await call(s, "query", {"get_name": "ID"})
    expect("Get.ID query handled", r.get("ok") is True, f"{r!r}")


async def main() -> None:
    async with streamablehttp_client(URL) as (rd, wr, _):
        async with ClientSession(rd, wr) as s:
            await s.initialize()
            probes = [
                probe_marker_outside_duration,
                probe_hierarchy_inverted,
                probe_hierarchy_zero_length,
                probe_undo_overflow,
                probe_redo_without_undo,
                probe_duplicate_marker_at_same_time,
                probe_set_duration_zero,
                probe_set_duration_negative,
                probe_set_duration_huge,
                probe_unicode_label,
                probe_invalid_color,
                probe_rapid_create_delete,
                probe_set_negative_height,
                probe_set_huge_height,
                # probe_zero_duration_then_create — skipped: hits the
                # set_duration hang (see scripts/mcp_repro_hang.py).
                probe_export_json_no_path,
                probe_query_unsupported_get,
            ]
            for p in probes:
                try:
                    await p(s)
                except Exception as exc:
                    print(f"[ERROR] probe {p.__name__}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
