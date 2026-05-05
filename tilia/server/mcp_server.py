"""Build a FastMCP server that bridges to a running TiLiA instance."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from tilia.requests import Get, Post, get as request_get, post as request_post
from tilia.server import extras, registry
from tilia.server.bridge import await_main
from tilia.ui import commands


def _jsonable(value: Any) -> Any:
    """Coerce arbitrary Python objects into JSON-serialisable form."""
    try:
        json.dumps(value)
        return value
    except TypeError:
        return json.loads(json.dumps(value, default=str))


def build(host: str = "127.0.0.1", port: int = 8765) -> FastMCP:
    mcp = FastMCP(
        name="tilia",
        instructions=(
            "Drive a running TiLiA application. `list_commands` enumerates "
            "the in-app command registry; `execute_command` invokes any of "
            "them on the Qt main thread. Resources under tilia:// expose the "
            "current media and timeline state."
        ),
        host=host,
        port=port,
    )

    @mcp.tool(description="List every command name registered with tilia.ui.commands.")
    async def list_commands() -> list[str]:
        names = await await_main(lambda: list(commands._name_to_callback.keys()))
        return sorted(names)

    @mcp.tool(
        description=(
            "Execute a registered TiLiA command. `name` is the dotted command "
            "name (see list_commands). `args` and `kwargs` are forwarded to "
            "the underlying callback. Commands that prompt the user via a "
            "modal dialog will block — pass any required values explicitly."
        )
    )
    async def execute_command(
        name: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            result = await await_main(
                commands.execute, name, *(args or []), **(kwargs or {})
            )
            return {"ok": True, "result": _jsonable(result)}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool(description="Open a .tla file at the given absolute path.")
    async def open_file(path: str) -> dict[str, Any]:
        try:
            await await_main(commands.execute, "file.open", path)
            return {"ok": True, "path": path}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool(description="Save current file (use save_as path to write a new copy).")
    async def save_file(path: str | None = None) -> dict[str, Any]:
        try:
            cmd = "file.save_as" if path else "file.save"
            args = [path] if path else []
            await await_main(commands.execute, cmd, *args)
            return {"ok": True, "path": path}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool(
        description=(
            "Add a new timeline. kind ∈ {marker, beat, hierarchy, harmony, "
            "pdf, score, audiowave}. Pass an explicit name to skip the name "
            "prompt dialog."
        )
    )
    async def add_timeline(kind: str, name: str = "") -> dict[str, Any]:
        try:
            await await_main(
                commands.execute, f"timelines.add.{kind}", name or f"{kind} timeline"
            )
            return {"ok": True, "kind": kind, "name": name}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool(description="Add a marker at `time` seconds on the first marker timeline.")
    async def add_marker(time: float) -> dict[str, Any]:
        try:
            await await_main(commands.execute, "timeline.marker.add", time)
            return {"ok": True, "time": time}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool(
        description=(
            "Set media duration without loading any media. Useful for "
            "automation or tests that want to add timelines without a "
            "media file."
        )
    )
    async def set_duration(seconds: float) -> dict[str, Any]:
        try:
            await await_main(request_post, Post.PLAYER_DURATION_AVAILABLE, seconds)
            return {"ok": True, "seconds": seconds}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @mcp.resource(
        "tilia://state",
        description="Full app state (timelines + media metadata) as JSON.",
        mime_type="application/json",
    )
    async def app_state() -> str:
        state = await await_main(request_get, Get.APP_STATE)
        return json.dumps(_jsonable(state), indent=2)

    @mcp.resource(
        "tilia://media/duration",
        description="Loaded media duration in seconds (0 if none).",
        mime_type="application/json",
    )
    async def media_duration() -> str:
        try:
            value = await await_main(request_get, Get.MEDIA_DURATION)
        except Exception:
            value = None
        return json.dumps({"duration": value})

    @mcp.resource(
        "tilia://media/current_time",
        description="Current playback time in seconds.",
        mime_type="application/json",
    )
    async def media_current_time() -> str:
        try:
            value = await await_main(request_get, Get.MEDIA_CURRENT_TIME)
        except Exception:
            value = None
        return json.dumps({"current_time": value})

    @mcp.resource(
        "tilia://media/path",
        description="Path/URL of the loaded media (null if none).",
        mime_type="application/json",
    )
    async def media_path() -> str:
        try:
            value = await await_main(request_get, Get.MEDIA_PATH)
        except Exception:
            value = None
        return json.dumps({"media_path": value})

    @mcp.resource(
        "tilia://commands",
        description="Sorted list of registered command names.",
        mime_type="application/json",
    )
    async def commands_list_resource() -> str:
        names = await await_main(lambda: list(commands._name_to_callback.keys()))
        return json.dumps(sorted(names))

    extras.register(mcp)
    registry.register(mcp)

    return mcp
