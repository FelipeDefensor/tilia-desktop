"""Marshal arbitrary callables onto the Qt main thread from worker threads.

The MCP server runs in its own thread and asyncio loop, but TiLiA's commands
and Get repliers all expect to run on the QApplication thread (they touch Qt
widgets, the timeline scene, etc.). `call_on_main` queues the callable via a
QObject signal connected with `Qt.QueuedConnection` and returns a
`concurrent.futures.Future` that resolves once the main thread runs it.

The module also captures `Post.DISPLAY_ERROR` so that automation never blocks
on a QMessageBox modal — errors land in `recent_errors` (read via the
tilia://errors resource) instead.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from concurrent.futures import Future
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot


class _MainThreadInvoker(QObject):
    invoke = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.invoke.connect(self._run, Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def _run(self, fn: Callable[[], None]) -> None:
        fn()


_invoker: _MainThreadInvoker | None = None


def install(parent: QObject | None = None) -> None:
    """Construct the invoker on the Qt main thread. Idempotent.

    Must be called from the Qt main thread before any worker thread calls
    `call_on_main` or `await_main`.
    """
    global _invoker
    if _invoker is not None:
        return
    _invoker = _MainThreadInvoker()
    if parent is not None:
        _invoker.setParent(parent)


def call_on_main(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
    if _invoker is None:
        raise RuntimeError("tilia.server.bridge.install() was not called")
    fut: Future = Future()

    def runner() -> None:
        try:
            fut.set_result(fn(*args, **kwargs))
        except BaseException as exc:
            fut.set_exception(exc)

    _invoker.invoke.emit(runner)
    return fut


async def await_main(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await asyncio.wrap_future(call_on_main(fn, *args, **kwargs))


# ------------------------- error capture -------------------------

recent_errors: deque[dict[str, Any]] = deque(maxlen=200)


class _ErrorCaptureSentinel:
    pass


_capture_owner = _ErrorCaptureSentinel()


def _capture_error(title: str, message: str) -> None:
    recent_errors.append(
        {"title": title, "message": message, "ts": time.time()}
    )
    try:
        from tilia.log import logger

        logger.warning(f"[mcp] suppressed dialog: {title}: {message[:200]}")
    except Exception:
        pass


def install_error_capture() -> None:
    """Replace every Post.DISPLAY_ERROR listener with a non-blocking capture.

    TiLiA's default listener pops a QMessageBox via .exec(), which blocks the
    Qt main thread. That breaks any automation flow that touches a validator
    or other guarded path. We swap in a capture-only listener for the lifetime
    of the server.
    """
    from tilia.requests import Post, listen
    from tilia.requests.post import _posts_to_listeners

    listeners = _posts_to_listeners.get(Post.DISPLAY_ERROR)
    if listeners is not None:
        listeners.clear()
    listen(_capture_owner, Post.DISPLAY_ERROR, _capture_error)
