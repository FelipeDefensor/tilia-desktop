"""Extra MCP tools that go beyond the registered command registry.

These are the granular hooks needed to drive TiLiA programmatically: direct
backend component creation (no dialogs), per-timeline introspection, window
resizing, region-cropped screenshots, repaint flushing.

Everything here lives behind `await_main` so that any Qt access happens on
the GUI thread.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP, Image
from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from tilia.requests import Get, Post, get as request_get, post as request_post
from tilia.server.bridge import await_main
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.timeline_kinds import TimelineKind


_KIND_NAME_TO_TLKIND = {
    "marker": TimelineKind.MARKER_TIMELINE,
    "beat": TimelineKind.BEAT_TIMELINE,
    "hierarchy": TimelineKind.HIERARCHY_TIMELINE,
    "harmony": TimelineKind.HARMONY_TIMELINE,
    "pdf": TimelineKind.PDF_TIMELINE,
    "score": TimelineKind.SCORE_TIMELINE,
    "audiowave": TimelineKind.AUDIOWAVE_TIMELINE,
    "slider": TimelineKind.SLIDER_TIMELINE,
}


def _flush_paint() -> None:
    app = QApplication.instance()
    if app is None:
        return
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    app.sendPostedEvents()
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return json.loads(json.dumps(value, default=str))


def _list_timeline_ids() -> list[int]:
    coll = request_get(Get.TIMELINE_COLLECTION)
    return [tl.id for tl in coll.get_timelines()]


def _summarize_timeline(tl: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": tl.id,
        "kind": tl.KIND.name,
        "name": getattr(tl, "name", ""),
        "height": getattr(tl, "height", None),
        "ordinal": getattr(tl, "ordinal", None),
        "is_visible": getattr(tl, "is_visible", None),
    }
    try:
        components = list(tl.component_manager._components)  # type: ignore[attr-defined]
        summary["component_count"] = len(components)
    except Exception:
        summary["component_count"] = None
    return summary


def register(mcp: FastMCP) -> None:
    """Attach all extra tools and resources to the given FastMCP instance."""

    # --------- introspection ---------

    @mcp.tool(description="List timelines with id, kind, name, height, ordinal, and component count.")
    async def list_timelines() -> list[dict[str, Any]]:
        def _do() -> list[dict[str, Any]]:
            coll = request_get(Get.TIMELINE_COLLECTION)
            return [_summarize_timeline(tl) for tl in coll.get_timelines()]

        return await await_main(_do)

    @mcp.tool(description="Look up a timeline id by exact name. Returns null if not found.")
    async def get_timeline_id_by_name(name: str) -> str | None:
        def _do() -> str | None:
            coll = request_get(Get.TIMELINE_COLLECTION)
            tl = coll.get_timeline_by_attr("name", name)
            return tl.id if tl is not None else None

        return await await_main(_do)

    @mcp.tool(description="Get all components of a timeline by id (full serialised data).")
    async def get_components(timeline_id: str) -> list[dict[str, Any]]:
        def _do() -> list[dict[str, Any]]:
            coll = request_get(Get.TIMELINE_COLLECTION)
            tl = coll.get_timeline(str(timeline_id))
            if tl is None:
                return []
            out: list[dict[str, Any]] = []
            for comp in tl.component_manager._components:  # type: ignore[attr-defined]
                payload = {"id": comp.id, "kind": comp.KIND.name}
                for attr in getattr(comp, "SERIALIZABLE", []):
                    try:
                        payload[attr] = _jsonable(comp.get_data(attr))
                    except Exception:
                        payload[attr] = None
                out.append(payload)
            return out

        return await await_main(_do)

    # --------- mutation: components ---------

    @mcp.tool(
        description=(
            "Create a hierarchy component directly with explicit bounds. "
            "Bypasses dialogs. Returns the new component id."
        )
    )
    async def create_hierarchy(
        timeline_id: str,
        start: float,
        end: float,
        level: int = 1,
        color: str = "",
        label: str = "",
    ) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            coll = request_get(Get.TIMELINE_COLLECTION)
            tl = coll.get_timeline(str(timeline_id))
            if tl is None:
                return {"ok": False, "error": f"no timeline with id {timeline_id}"}
            comp, reason = tl.create_component(
                ComponentKind.HIERARCHY,
                start=start,
                end=end,
                level=level,
                color=color,
                label=label,
            )
            if comp is None:
                return {"ok": False, "error": reason}
            return {"ok": True, "id": comp.id}

        try:
            return await await_main(_do)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool(
        description=(
            "Create a marker component directly. timeline_id is the marker "
            "timeline. Returns the new component id."
        )
    )
    async def create_marker(
        timeline_id: str,
        time_seconds: float,
        label: str = "",
        color: str = "",
    ) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            coll = request_get(Get.TIMELINE_COLLECTION)
            tl = coll.get_timeline(str(timeline_id))
            if tl is None:
                return {"ok": False, "error": f"no timeline with id {timeline_id}"}
            comp, reason = tl.create_component(
                ComponentKind.MARKER,
                time=time_seconds,
                label=label,
                color=color or None,
            )
            if comp is None:
                return {"ok": False, "error": reason}
            return {"ok": True, "id": comp.id}

        try:
            return await await_main(_do)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool(description="Set a single attribute on a component (e.g. color, label, level).")
    async def set_component_data(
        timeline_id: str, component_id: str, attr: str, value: Any
    ) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            coll = request_get(Get.TIMELINE_COLLECTION)
            tl = coll.get_timeline(str(timeline_id))
            if tl is None:
                return {"ok": False, "error": f"no timeline with id {timeline_id}"}
            try:
                tl.set_component_data(str(component_id), attr, value)
                return {"ok": True}
            except Exception as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        return await await_main(_do)

    @mcp.tool(description="Delete a component by id from a timeline.")
    async def delete_component(timeline_id: str, component_id: str) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            coll = request_get(Get.TIMELINE_COLLECTION)
            tl = coll.get_timeline(str(timeline_id))
            if tl is None:
                return {"ok": False, "error": f"no timeline with id {timeline_id}"}
            comp = tl.get_component(str(component_id))
            if comp is None:
                return {"ok": False, "error": f"no component with id {component_id}"}
            tl.delete_components([comp])
            return {"ok": True}

        try:
            return await await_main(_do)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # --------- mutation: timelines ---------

    @mcp.tool(description="Set a single attribute on a timeline (e.g. height, name, is_visible, ordinal).")
    async def set_timeline_data(timeline_id: str, attr: str, value: Any) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            coll = request_get(Get.TIMELINE_COLLECTION)
            try:
                ok = coll.set_timeline_data(timeline_id, attr, value)
                return {"ok": bool(ok) if ok is not None else True}
            except Exception as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        return await await_main(_do)

    @mcp.tool(
        description=(
            "Create a timeline directly without dialogs. kind ∈ {marker, beat, "
            "hierarchy, harmony, pdf, score, audiowave, slider}. Returns the "
            "new timeline id."
        )
    )
    async def create_timeline(kind: str, name: str = "") -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            tlkind = _KIND_NAME_TO_TLKIND.get(kind)
            if tlkind is None:
                return {"ok": False, "error": f"unknown kind {kind!r}"}
            coll = request_get(Get.TIMELINE_COLLECTION)
            tl = coll.create_timeline(kind=tlkind, name=name or kind.title())
            return {"ok": True, "id": tl.id, "kind": tlkind.name}

        try:
            return await await_main(_do)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool(description="Delete a timeline by id.")
    async def delete_timeline(timeline_id: str) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            coll = request_get(Get.TIMELINE_COLLECTION)
            tl = coll.get_timeline(str(timeline_id))
            if tl is None:
                return {"ok": False, "error": f"no timeline with id {timeline_id}"}
            coll.delete_timeline(tl)
            return {"ok": True}

        try:
            return await await_main(_do)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool(description="Clear every timeline (delete all of them).")
    async def clear_all_timelines() -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            from tilia.requests import post

            post(Post.APP_CLEAR)
            return {"ok": True}

        try:
            return await await_main(_do)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # --------- window control ---------

    @mcp.tool(description="Resize the main window to (width, height) in pixels.")
    async def resize_window(width: int, height: int) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            window = request_get(Get.MAIN_WINDOW)
            window.resize(int(width), int(height))
            _flush_paint()
            return {"ok": True, "size": [window.width(), window.height()]}

        try:
            return await await_main(_do)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool(description="Return current main window size and position.")
    async def get_window_geometry() -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            window = request_get(Get.MAIN_WINDOW)
            geom = window.geometry()
            return {
                "x": geom.x(),
                "y": geom.y(),
                "width": geom.width(),
                "height": geom.height(),
            }

        return await await_main(_do)

    @mcp.tool(description="Zoom out N times (calls view.zoom.out N times).")
    async def zoom_out(times: int = 1) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            from tilia.ui import commands

            for _ in range(max(1, int(times))):
                commands.execute("view.zoom.out")
            return {"ok": True}

        try:
            return await await_main(_do)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool(description="Zoom in N times (calls view.zoom.in N times).")
    async def zoom_in(times: int = 1) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            from tilia.ui import commands

            for _ in range(max(1, int(times))):
                commands.execute("view.zoom.in")
            return {"ok": True}

        try:
            return await await_main(_do)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool(
        description=(
            "Fit the timeline view so the full duration is visible in one screen. "
            "Repeats view.zoom.out until the visible viewport covers the duration."
        )
    )
    async def fit_to_duration(max_steps: int = 30) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            from tilia.ui import commands

            window = request_get(Get.MAIN_WINDOW)
            for _ in range(max_steps):
                _flush_paint()
                viewport_w = window.centralWidget().viewport().width() if hasattr(window.centralWidget(), "viewport") else window.width()
                try:
                    timeline_w = request_get(Get.TIMELINE_WIDTH)
                except Exception:
                    timeline_w = viewport_w
                if timeline_w <= viewport_w + 4:
                    return {"ok": True, "viewport": viewport_w, "timeline": timeline_w}
                commands.execute("view.zoom.out")
            return {"ok": True, "viewport": viewport_w, "timeline": timeline_w, "note": "max_steps reached"}

        try:
            return await await_main(_do)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # --------- screenshot ---------

    def _take(target: str, target_id: int | None) -> tuple[str, str]:
        """Return (path, target_repr). Runs on the Qt main thread."""
        _flush_paint()
        window = request_get(Get.MAIN_WINDOW)
        widget = window
        repr_ = "window"
        if target == "timelines":
            widget = window.centralWidget()
            repr_ = "timelines"
        elif target == "timeline" and target_id is not None:
            coll = request_get(Get.TIMELINE_COLLECTION)
            tl = coll.get_timeline(str(target_id))
            if tl is None:
                raise ValueError(f"no timeline with id {target_id}")
            try:
                tl_ui = request_get(Get.TIMELINE_UI, str(target_id))
                widget = tl_ui.view if hasattr(tl_ui, "view") else widget
            except Exception:
                pass
            repr_ = f"timeline:{target_id}"
        pixmap = widget.grab()
        out_dir = Path(tempfile.gettempdir())
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"tilia-{int(time.time() * 1000)}.png"
        pixmap.save(str(path), "PNG")
        return str(path), repr_

    @mcp.tool(
        description=(
            "Capture a PNG of the running app. target ∈ {window, timelines, "
            "timeline}. For target='timeline' pass timeline_id. Inline image "
            "content is returned alongside the file path."
        )
    )
    async def screenshot(
        target: str = "window",
        timeline_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            path, repr_ = await await_main(_take, target, timeline_id)
            return {
                "ok": True,
                "path": path,
                "target": repr_,
                "image": Image(path=path).to_image_content().model_dump(),
            }
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool(description="Force a Qt repaint pass (useful between rapid mutations and screenshots).")
    async def flush_paint() -> dict[str, Any]:
        await await_main(_flush_paint)
        return {"ok": True}

    # --------- generic Get exposure ---------

    @mcp.tool(
        description=(
            "Read any tilia.requests.Get value by enum name. "
            "FROM_USER_* keys are blocked because they pop modal dialogs."
        )
    )
    async def query(get_name: str) -> dict[str, Any]:
        if get_name.startswith("FROM_USER_"):
            return {"ok": False, "error": "FROM_USER_* keys are blocked (modal)"}
        try:
            key = Get[get_name]
        except KeyError:
            return {"ok": False, "error": f"unknown Get key {get_name!r}"}

        def _do() -> Any:
            return request_get(key)

        try:
            value = await await_main(_do)
            return {"ok": True, "value": _jsonable(value)}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool(description="List every Get enum name (skipping FROM_USER_* prompt keys).")
    async def list_query_keys() -> list[str]:
        return [g.name for g in Get if not g.name.startswith("FROM_USER_")]

    # --------- captured errors ---------

    @mcp.tool(description="Recent errors that would have surfaced as modal dialogs.")
    async def recent_errors(limit: int = 50) -> list[dict[str, Any]]:
        from tilia.server.bridge import recent_errors as buf

        return list(buf)[-int(limit):]

    @mcp.tool(description="Clear the captured-errors buffer.")
    async def clear_recent_errors() -> dict[str, Any]:
        from tilia.server.bridge import recent_errors as buf

        buf.clear()
        return {"ok": True}

    @mcp.resource(
        "tilia://errors",
        description="Recent errors captured from Post.DISPLAY_ERROR (modal dialogs suppressed).",
        mime_type="application/json",
    )
    async def errors_resource() -> str:
        from tilia.server.bridge import recent_errors as buf

        return json.dumps(list(buf))
