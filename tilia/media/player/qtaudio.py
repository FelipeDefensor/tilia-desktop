"""QtAudioPlayer with pitch-preserved playback rate.

QMediaPlayer's native ``setPlaybackRate`` changes pitch as a side
effect (it just plays samples faster / slower). For music-theory
transcription users the opposite is wanted: keep the pitch, change
the duration. We achieve that by rendering a time-stretched WAV once
per rate (via rubberband or ffmpeg ``atempo``; see
``tilia.media.player.stretch``) and switching the QMediaPlayer's
source to that file while reporting the original-media timeline
to the rest of the app.

Rendering runs in a ``QThreadPool`` worker so the UI doesn't freeze
for the few seconds it takes ffmpeg / rubberband to decode + stretch
a typical song. When media loads, a small set of common transcription
rates is queued for preemptive rendering so the user usually doesn't
wait at all on the second rate change.

Time-coordinate convention: TiLiA tracks current_time and durations
in *original-media seconds*. When the loaded source is a stretched
file, Qt's position / duration are in stretched-file seconds. We
convert at every boundary:

    original_time = stretched_time * rate
    stretched_time = original_time / rate

That way components, hover, seek, etc. all keep working in
original-media time regardless of the current rate.
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QCursor
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

import tilia.errors
from tilia.media.player.qtplayer import QtPlayer, wait_for_signal
from tilia.media.player.stretch import (
    StretchError,
    is_stretch_available,
    render_stretched,
)
from tilia.requests import Post, post

# Rates pre-rendered in the background after media load. The slow side
# matters most for transcription — picking 0.5/0.75 should feel
# instant. Faster rates are cheaper to render but less commonly used,
# so we include only a small selection.
PREEMPTIVE_RATES: tuple[float, ...] = (0.5, 0.75, 1.25, 1.5)


class _RenderSignals(QObject):
    finished = Signal(float, str)  # (rate, output path)
    failed = Signal(float, str)  # (rate, error message)


class _RenderRunnable(QRunnable):
    def __init__(self, src: str, rate: float, signals: _RenderSignals) -> None:
        super().__init__()
        self.src = src
        self.rate = rate
        self.signals = signals

    @Slot()
    def run(self) -> None:
        try:
            out = render_stretched(self.src, self.rate)
        except StretchError as e:
            self.signals.failed.emit(self.rate, str(e))
            return
        self.signals.finished.emit(self.rate, str(out))


class QtAudioPlayer(QtPlayer):
    MEDIA_TYPE = "audio"

    def __init__(self):
        super().__init__()
        self._original_source: str | None = None
        self._original_duration: float = 0.0
        self._rate: float = 1.0
        # `_pending_rate` is the most recently requested rate; render
        # completions only swap to their result when it still matches
        # (stale renders fall through to the cache for later use).
        self._pending_rate: float = 1.0
        self._rate_cache: dict[tuple[str, float], Path] = {}
        # Track which (source, rate) workers are already in flight so a
        # second pick of the same rate doesn't spawn a duplicate.
        self._in_flight: set[tuple[str, float]] = set()
        # Keep signal objects alive so their slot connections survive.
        # (PySide6 GC's QObjects whose Python references drop.)
        self._signal_keepalive: list[_RenderSignals] = []
        # The rate the user is actively waiting on (vs. background
        # preemptive renders, which the user didn't ask for). Used to
        # decide whether to escalate UI feedback — busy cursor, status
        # message, error toast on failure. None means no user is
        # currently waiting on any render.
        self._user_wait_rate: float | None = None
        # Whether we've pushed a WaitCursor onto QApplication's stack.
        # Tracked separately so we can pop exactly as many as we
        # pushed (Qt's cursor stack is LIFO; mismatched push/pop leaves
        # a sticky wait cursor for the rest of the session).
        self._cursor_pushed: bool = False

    # --- media lifecycle -------------------------------------------------

    def _engine_load_media(self, media_path: str) -> bool:
        ok = super()._engine_load_media(media_path)
        if ok:
            self._original_source = media_path
            self._original_duration = self.player.duration() / 1000
            self._rate = 1.0
            self._pending_rate = 1.0
            self._clear_cache()
            self._queue_preemptive_renders()
        return ok

    def _engine_unload_media(self):
        super()._engine_unload_media()
        self._original_source = None
        self._original_duration = 0.0
        self._rate = 1.0
        self._pending_rate = 1.0
        self._clear_cache()

    def _engine_exit(self):
        super()._engine_exit()
        self._clear_cache()

    def _clear_cache(self) -> None:
        for path in self._rate_cache.values():
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                # Best-effort: a temp file we couldn't remove will be
                # garbage-collected by the OS eventually. Don't let
                # cleanup failures break unload.
                pass
        self._rate_cache.clear()
        self._in_flight.clear()
        self._signal_keepalive.clear()
        # Drop any pending busy cursor so the user doesn't end up with
        # a stuck WaitCursor after closing a file mid-render.
        self._set_user_wait_rate(None)

    # --- user-wait + cursor management -----------------------------------

    def _set_user_wait_rate(self, rate: float | None) -> None:
        """Mark which rate the user is actively waiting on.

        Calling with a non-None ``rate`` pushes an app-wide ``WaitCursor``
        if one isn't already pushed; calling with ``None`` pops it. The
        cursor is the loudest non-blocking signal Qt gives us and pairs
        with the status-bar message to make it unmistakable that the
        rate change is being processed (the status bar alone proved too
        subtle in practice).
        """
        self._user_wait_rate = rate

        if rate is not None and not self._cursor_pushed:
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
            self._cursor_pushed = True
        elif rate is None and self._cursor_pushed:
            QApplication.restoreOverrideCursor()
            self._cursor_pushed = False

    # --- time conversion -------------------------------------------------

    def _engine_get_current_time(self):
        return self.player.position() / 1000 * self._rate

    def _engine_seek(self, time: float) -> None:
        self.player.setPosition(int(time / self._rate * 1000))

    def _engine_get_media_duration(self) -> float:
        return self._original_duration or super()._engine_get_media_duration()

    # --- rate change -----------------------------------------------------

    def _engine_try_playback_rate(self, rate: float) -> None:
        if not self._original_source:
            # No media yet — store as a no-op; the spinbox only fires
            # this with media loaded in practice.
            return

        self._pending_rate = rate

        if math.isclose(rate, 1.0):
            # An earlier "Rendering at X×" message could still be
            # showing from a render the user is now abandoning. Clear
            # it (and any busy cursor) so the status bar doesn't lie.
            self._set_user_wait_rate(None)
            post(Post.STATUS_MESSAGE_CLEAR)
            self._swap_source(self._original_source, rate=1.0)
            return

        # Cache hit: swap immediately. This is the path that should be
        # hit most of the time once preemptive renders complete.
        key = (self._original_source, rate)
        cached = self._rate_cache.get(key)
        if cached is not None and cached.exists():
            self._set_user_wait_rate(None)
            post(Post.STATUS_MESSAGE_CLEAR)
            self._swap_source(str(cached), rate=rate)
            return

        if not is_stretch_available():
            # No engine — fall back to native (pitch-warping) rate.
            # Better than refusing to play at all.
            self._set_user_wait_rate(None)
            tilia.errors.display(tilia.errors.STRETCH_UNAVAILABLE)
            super()._engine_try_playback_rate(rate)
            return

        # Start a background render; the spinbox returns immediately,
        # the UI stays responsive, and we swap when the worker reports
        # done (provided the user hasn't picked a different rate
        # meanwhile). Push a busy cursor + status message so the user
        # can see the request was received — the status bar alone is
        # too easy to miss.
        self._set_user_wait_rate(rate)
        post(
            Post.STATUS_MESSAGE_SET,
            f"Rendering audio at {rate}× (pitch-preserved)",
            -1.0,
        )
        self._start_render(rate, user_initiated=True)

    def _start_render(self, rate: float, user_initiated: bool) -> None:
        """Queue a render worker for ``rate``. Idempotent: if a worker
        for the same (source, rate) is already running we just return —
        the existing one's completion handler will swap if it's the
        user's current target."""
        key = (self._original_source, rate)
        if key in self._in_flight or self._rate_cache.get(key) is not None:
            return

        signals = _RenderSignals()
        signals.finished.connect(
            lambda r, p: self._on_render_done(r, p, user_initiated)
        )
        signals.failed.connect(
            lambda r, msg: self._on_render_failed(r, msg, user_initiated)
        )
        self._signal_keepalive.append(signals)
        self._in_flight.add(key)
        QThreadPool.globalInstance().start(
            _RenderRunnable(self._original_source, rate, signals)
        )

    def _queue_preemptive_renders(self) -> None:
        """Kick off background renders for common transcription rates
        right after a media file loads. Best-effort: if engines are
        missing or renders fail, the user just experiences the regular
        on-demand latency on first use."""
        if not is_stretch_available() or not self._original_source:
            return
        for rate in PREEMPTIVE_RATES:
            self._start_render(rate, user_initiated=False)

    def _on_render_done(self, rate: float, path: str, user_initiated: bool) -> None:
        # The worker's emitted source path may belong to a previously-
        # loaded file. We only cache against the *current* source, so
        # a swap-out-then-load-new-file sequence doesn't leave stale
        # entries behind that we'd never look up anyway.
        if self._original_source is None:
            return
        key = (self._original_source, rate)
        self._in_flight.discard(key)
        self._rate_cache[key] = Path(path)

        # Only clear the "Rendering…" message when the user's pending
        # rate is satisfied — otherwise a stale completion would wipe
        # the message for the rate the user is *actually* still waiting
        # on, leaving them staring at a silent status bar.
        if math.isclose(self._pending_rate, rate):
            # The user might be waiting on this completion even if the
            # *worker* was preemptive — they picked the rate after the
            # preemptive started, so the signal was bound with
            # user_initiated=False but the user is still waiting. Check
            # _user_wait_rate (instance state) instead of trusting the
            # bound-at-creation flag.
            if self._user_wait_rate is not None and math.isclose(
                self._user_wait_rate, rate
            ):
                self._set_user_wait_rate(None)
                post(Post.STATUS_MESSAGE_CLEAR)
            self._swap_source(path, rate=rate)

    def _on_render_failed(self, rate: float, msg: str, user_initiated: bool) -> None:
        if self._original_source is not None:
            self._in_flight.discard((self._original_source, rate))

        # Use the instance-level wait-rate state rather than the
        # signal's captured `user_initiated` flag (see _on_render_done's
        # comment): a preemptive render the user is now waiting on
        # should still surface its error, and a user-initiated render
        # the user has since abandoned shouldn't.
        if self._user_wait_rate is None or not math.isclose(self._user_wait_rate, rate):
            return

        self._set_user_wait_rate(None)
        post(Post.STATUS_MESSAGE_CLEAR)
        tilia.errors.display(tilia.errors.STRETCH_FAILED, msg)
        # Surface *something* — the user picked a non-unit rate; fall
        # back to Qt's native (pitch-warping) rate so playback doesn't
        # appear to do nothing.
        if math.isclose(self._pending_rate, rate):
            super()._engine_try_playback_rate(rate)

    def _swap_source(self, path: str, rate: float) -> None:
        """Replace the QMediaPlayer source while preserving playback
        position (in original-media time) and play/pause state.

        Qt's ``QMediaPlayer.setSource`` is asynchronous; we wait for the
        new media's ``LoadedMedia`` status before seeking, otherwise the
        seek silently no-ops.

        If the requested source URL already matches the current one,
        only the rate bookkeeping is updated — calling ``setSource``
        with the same URL wouldn't re-emit ``LoadedMedia``, which would
        then time out ``wait_for_signal``.
        """
        target = QUrl.fromLocalFile(path)
        if self.player.source() == target and math.isclose(self._rate, rate):
            return

        was_playing = self.is_playing
        # Snapshot original-media time before we change `self._rate` —
        # otherwise the conversion uses the *new* rate against the
        # *old* stretched-file position.
        current_original_time = self._engine_get_current_time()

        if was_playing:
            self._engine_pause()

        if self.player.source() != target:

            @wait_for_signal(
                self.player.mediaStatusChanged, QMediaPlayer.MediaStatus.LoadedMedia
            )
            def load():
                self.player.setSource(target)
                return True

            load()

        self._rate = rate
        self._engine_seek(current_original_time)

        if was_playing:
            self._engine_play()
