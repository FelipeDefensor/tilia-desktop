"""Boot helper: install the main-thread bridge and run FastMCP in a daemon thread."""

from __future__ import annotations

import asyncio
import threading

from PySide6.QtCore import QObject

from tilia.log import logger
from tilia.server import bridge


def start(
    host: str = "127.0.0.1",
    port: int = 8765,
    parent: QObject | None = None,
) -> threading.Thread:
    """Start the MCP server. Must be called from the Qt main thread before exec()."""
    bridge.install(parent=parent)
    bridge.install_error_capture()

    from tilia.server.mcp_server import build

    server = build(host=host, port=port)

    def _run() -> None:
        try:
            asyncio.run(server.run_streamable_http_async())
        except Exception:
            logger.exception("MCP server crashed")

    thread = threading.Thread(target=_run, name="tilia-mcp-server", daemon=True)
    thread.start()
    logger.info(f"MCP server listening on http://{host}:{port}/mcp")
    return thread
