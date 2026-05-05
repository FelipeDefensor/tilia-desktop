"""MCP server for driving a running TiLiA instance.

The server exposes the registered command registry (`tilia.ui.commands`) as
MCP tools and a handful of `Get` queries as resources, so an external client
(e.g. Claude Code, an automation script) can read app state and execute
user-level actions on a running TiLiA without touching internal APIs.

Enable with `tilia --mcp-server` (default port 8765, localhost only).
"""

from tilia.server.runner import start

__all__ = ["start"]
