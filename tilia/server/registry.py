"""Expose every entry in tilia.ui.commands as its own MCP tool.

Each registered command becomes a tool named `cmd__<sanitized_dotted_name>`
(dots → double underscore). The tool accepts a generic `args` list and
`kwargs` dict that get forwarded to the underlying callback. The
description records the original dotted name and the inspected callback
signature so an MCP client (or LLM) can pick reasonable arguments.

This sits alongside the curated tools in mcp_server.py / extras.py — those
typed wrappers stay for ergonomics, and the registry adds breadth.
"""

from __future__ import annotations

import functools
import inspect
import re
from typing import Any

from mcp.server.fastmcp import FastMCP

from tilia.server.bridge import await_main
from tilia.ui import commands


_SANITIZE = re.compile(r"[^A-Za-z0-9_]+")


def _tool_name(command_name: str) -> str:
    return "cmd__" + _SANITIZE.sub("_", command_name.replace(".", "__"))


def _describe(command_name: str, callback: Any) -> str:
    # Walk through partials to reach the underlying callable.
    fn = callback
    bound_args: tuple = ()
    bound_kwargs: dict[str, Any] = {}
    while isinstance(fn, functools.partial):
        bound_args = fn.args + bound_args  # outermost wins for tracing
        bound_kwargs = {**fn.keywords, **bound_kwargs}
        fn = fn.func
    try:
        sig = inspect.signature(fn)
        sig_str = f"{getattr(fn, '__name__', repr(fn))}{sig}"
    except (TypeError, ValueError):
        sig_str = f"{getattr(fn, '__name__', repr(fn))}(?)"
    parts = [
        f"Command: {command_name}",
        f"Callback: {sig_str}",
    ]
    if bound_args or bound_kwargs:
        parts.append(f"Pre-bound: args={bound_args!r}, kwargs={bound_kwargs!r}")
    parts.append(
        "Pass `args` (list) and/or `kwargs` (dict) for any unbound parameters."
    )
    return "\n".join(parts)


def _make_tool(command_name: str):
    async def tool(
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            result = await await_main(
                commands.execute, command_name, *(args or []), **(kwargs or {})
            )
            try:
                import json

                json.dumps(result)
                payload = result
            except TypeError:
                payload = repr(result)
            return {"ok": True, "command": command_name, "result": payload}
        except Exception as exc:
            return {
                "ok": False,
                "command": command_name,
                "error": f"{type(exc).__name__}: {exc}",
            }

    tool.__name__ = _tool_name(command_name)
    return tool


def register(mcp: FastMCP) -> None:
    """Iterate the live command registry and add one MCP tool per entry."""
    for command_name, callback in sorted(commands._name_to_callback.items()):
        if callback is None:
            continue
        tool = _make_tool(command_name)
        mcp.tool(
            name=_tool_name(command_name),
            description=_describe(command_name, callback),
        )(tool)
