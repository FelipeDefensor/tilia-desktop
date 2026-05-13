"""Tests for `QtAudioPlayer`'s pitch-preserving playback rate.

Exercises the source-swap logic, the time-coordinate conversion that
keeps the rest of TiLiA seeing original-media seconds, and the
background-render dispatch (preemptive + on-demand).

The real rendering pipeline (rubberband / ffmpeg shell-out) is mocked
out — those engines are covered by `test_stretch.py`. Here we care
about *what* `_engine_try_playback_rate` does with the result and
*when* it spawns / consumes a worker, not how the result was produced.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tilia.media.player.qtaudio import QtAudioPlayer


@pytest.fixture
def player(tilia) -> QtAudioPlayer:
    """The shared ``QtAudioPlayer`` from the `tilia` fixture, reset to
    the rate-state any of these tests assumes."""
    p = tilia.player
    yield p
    p._original_source = None
    p._original_duration = 0.0
    p._rate = 1.0
    p._pending_rate = 1.0
    p._rate_cache.clear()
    p._in_flight.clear()
    p._signal_keepalive.clear()
    # If a test left the busy cursor pushed (e.g. the user-initiated
    # render handler didn't reach the matching completion path), pop
    # it so the next test starts clean.
    p._set_user_wait_rate(None)


def _set_loaded(player: QtAudioPlayer, source: str, duration: float, rate: float = 1.0):
    """Stage the player's bookkeeping as if a media file were loaded.
    Doesn't actually load anything through QMediaPlayer — that path
    needs real files and is covered by the broader player tests."""
    player._original_source = source
    player._original_duration = duration
    player._rate = rate
    player._pending_rate = rate


def _patch_threadpool_to_run_synchronously():
    """Replace ``QThreadPool.globalInstance().start`` with an immediate
    in-thread call to ``runnable.run()``. This lets tests verify the
    full worker → signal → handler chain deterministically without
    actually scheduling a thread."""
    return patch("tilia.media.player.qtaudio.QThreadPool.globalInstance")


class TestTimeCoordinateConversion:
    """`_engine_get_current_time` and `_engine_seek` must translate
    between original-media time (what the rest of TiLiA tracks) and
    stretched-file time (what Qt actually plays)."""

    def test_current_time_scales_by_rate(self, player):
        # Stretched file is 2× as long at rate 0.5; halfway through the
        # stretched file (position=20000ms) corresponds to original t=10.
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=0.5)
        with patch.object(player.player, "position", return_value=20000):
            assert player._engine_get_current_time() == 10.0

    def test_current_time_passes_through_at_rate_one(self, player):
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        with patch.object(player.player, "position", return_value=12345):
            assert player._engine_get_current_time() == 12.345

    def test_seek_converts_original_to_stretched(self, player):
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=0.5)
        with patch.object(player.player, "setPosition") as set_pos:
            player._engine_seek(10.0)
        # rate=0.5 → stretched file is 2× as long, so original time 10
        # lives at stretched position 20.
        set_pos.assert_called_once_with(20000)

    def test_seek_converts_speedup_correctly(self, player):
        # Regression: a previous version of the rubberband call inverted
        # the rate, which made the stretched file's duration disagree
        # with this conversion. Both directions need to round-trip.
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=2.0)
        with patch.object(player.player, "setPosition") as set_pos:
            player._engine_seek(10.0)
        # rate=2.0 → stretched file is half as long, so original t=10
        # lives at stretched position 5.
        set_pos.assert_called_once_with(5000)

    def test_duration_returns_original_not_stretched(self, player):
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=0.5)
        # Even if Qt's internal duration is 40s (stretched), TiLiA sees
        # the original 20s.
        assert player._engine_get_media_duration() == 20.0


class TestPlaybackRateDispatch:
    def test_no_op_when_no_media_loaded(self, player):
        # Should not blow up trying to render with no source.
        player._engine_try_playback_rate(0.5)
        assert player._rate == 1.0
        assert player._original_source is None

    def test_rate_one_swaps_back_to_original(self, player):
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=0.5)
        with patch.object(player, "_swap_source") as swap:
            player._engine_try_playback_rate(1.0)
        swap.assert_called_once_with("/tmp/song.mp3", rate=1.0)

    def test_cache_hit_swaps_immediately_without_worker(self, player, tmp_path):
        rendered = tmp_path / "cached.wav"
        rendered.write_bytes(b"")
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        player._rate_cache[("/tmp/song.mp3", 0.5)] = rendered

        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
            patch.object(player, "_swap_source") as swap,
        ):
            player._engine_try_playback_rate(0.5)

        swap.assert_called_once_with(str(rendered), rate=0.5)
        pool.return_value.start.assert_not_called()

    def test_cold_miss_queues_worker_and_swaps_on_completion(self, player, tmp_path):
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        rendered = tmp_path / "0.5x.wav"
        rendered.write_bytes(b"")

        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch(
                "tilia.media.player.qtaudio.render_stretched", return_value=rendered
            ) as render,
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
            patch.object(player, "_swap_source") as swap,
        ):
            # Make the pool execute the runnable inline so the test
            # observes the full finished-signal → swap chain.
            pool.return_value.start = lambda runnable: runnable.run()

            player._engine_try_playback_rate(0.5)

        render.assert_called_once_with("/tmp/song.mp3", 0.5)
        swap.assert_called_once_with(str(rendered), rate=0.5)
        assert player._rate_cache[("/tmp/song.mp3", 0.5)] == rendered

    def test_stale_render_completion_does_not_swap(self, player, tmp_path):
        # User picks 0.5, then quickly switches to 0.75 before 0.5
        # finishes. When 0.5 completes, it should populate the cache
        # but NOT swap (the user no longer wants 0.5).
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        slow_rendered = tmp_path / "0.5x.wav"
        slow_rendered.write_bytes(b"")

        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch(
                "tilia.media.player.qtaudio.render_stretched",
                return_value=slow_rendered,
            ),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
            patch.object(player, "_swap_source") as swap,
        ):
            captured: list = []
            pool.return_value.start = lambda runnable: captured.append(runnable)

            player._engine_try_playback_rate(0.5)
            # User changes their mind before the runnable executes.
            player._pending_rate = 0.75

            # Now let the 0.5 worker finish.
            captured[0].run()

        swap.assert_not_called()
        assert player._rate_cache[("/tmp/song.mp3", 0.5)] == slow_rendered

    def test_stale_completion_does_not_clear_status_message(self, player, tmp_path):
        # If a stale completion fires the STATUS_MESSAGE_CLEAR, the
        # user would see no progress indicator even though their
        # *current* pending render is still running. The message should
        # stay until the matching rate completes.
        from tilia.requests import Post, listen, stop_listening

        class _ClearSink:
            def __init__(self):
                self.count = 0

            def hit(self):
                self.count += 1

        sink = _ClearSink()
        listen(sink, Post.STATUS_MESSAGE_CLEAR, sink.hit)
        try:
            _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
            stale_rendered = tmp_path / "0.5x.wav"
            stale_rendered.write_bytes(b"")

            with (
                patch(
                    "tilia.media.player.qtaudio.is_stretch_available", return_value=True
                ),
                patch(
                    "tilia.media.player.qtaudio.render_stretched",
                    return_value=stale_rendered,
                ),
                patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
                patch.object(player, "_swap_source"),
            ):
                captured: list = []
                pool.return_value.start = lambda runnable: captured.append(runnable)

                player._engine_try_playback_rate(0.5)
                # User picks something else before 0.5 finishes.
                player._pending_rate = 0.75
                sink.count = 0  # ignore any clears that happened pre-stale

                # Stale completion arrives.
                captured[0].run()

            assert sink.count == 0, (
                "Stale completion cleared the status bar; the user would "
                "lose feedback for their actually-pending render."
            )
        finally:
            stop_listening(sink, Post.STATUS_MESSAGE_CLEAR)

    def test_duplicate_request_skips_second_worker(self, player, tmp_path):
        # User clicks the same rate twice in a row before the first
        # render completes. Don't spawn a second worker (they'd both
        # decode + stretch the same file).
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)

        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
        ):
            started: list = []
            pool.return_value.start = lambda runnable: started.append(runnable)

            player._engine_try_playback_rate(0.5)
            player._engine_try_playback_rate(0.5)

        assert len(started) == 1

    def test_no_engine_falls_back_to_native_rate(self, player, tilia_errors):
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        with (
            patch(
                "tilia.media.player.qtaudio.is_stretch_available", return_value=False
            ),
            patch.object(player.player, "setPlaybackRate") as native,
        ):
            player._engine_try_playback_rate(0.5)

        native.assert_called_once_with(0.5)
        tilia_errors.assert_error()
        tilia_errors.assert_in_error_title("Pitch")

    def test_render_failure_falls_back_to_native(self, player, tilia_errors, tmp_path):
        from tilia.media.player.stretch import StretchError

        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch(
                "tilia.media.player.qtaudio.render_stretched",
                side_effect=StretchError("boom"),
            ),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
            patch.object(player.player, "setPlaybackRate") as native,
        ):
            pool.return_value.start = lambda runnable: runnable.run()
            player._engine_try_playback_rate(0.5)

        native.assert_called_once_with(0.5)
        tilia_errors.assert_error()

    def test_unexpected_render_exception_does_not_escape_worker(
        self, player, tilia_errors
    ):
        # Regression for the silent audio-open crash: any exception
        # other than StretchError used to escape `_RenderRunnable.run`
        # and reach the QThreadPool worker thread, where some
        # PySide6 / Qt builds convert it into an unceremonious process
        # termination. Force a PermissionError (the shape produced by
        # the partial-file race) and verify it's routed through the
        # same failed-signal path StretchError takes.
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch(
                "tilia.media.player.qtaudio.render_stretched",
                side_effect=PermissionError("temp file locked"),
            ),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
            patch.object(player.player, "setPlaybackRate") as native,
        ):
            pool.return_value.start = lambda runnable: runnable.run()
            # Must not raise; fallback to native playback should still fire.
            player._engine_try_playback_rate(0.5)

        native.assert_called_once_with(0.5)
        tilia_errors.assert_error()


class TestPreemptiveRenders:
    def test_load_kicks_off_workers_for_common_rates(self, player):
        # `_engine_load_media` is the real one (calls into QMediaPlayer);
        # to avoid loading a real file, drive the post-load hook
        # directly. The hook is what queues the preemptive workers.
        from tilia.media.player.qtaudio import PREEMPTIVE_RATES

        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)

        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
        ):
            queued: list = []
            pool.return_value.start = lambda runnable: queued.append(runnable.rate)

            player._queue_preemptive_renders()

        assert sorted(queued) == sorted(PREEMPTIVE_RATES)

    def test_preemptive_failures_do_not_show_errors(
        self, player, tilia_errors, tmp_path
    ):
        from tilia.media.player.stretch import StretchError

        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)

        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch(
                "tilia.media.player.qtaudio.render_stretched",
                side_effect=StretchError("background boom"),
            ),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
        ):
            pool.return_value.start = lambda runnable: runnable.run()
            player._queue_preemptive_renders()

        # User didn't ask for any of these; a noisy error dialog for
        # each one would be terrible UX.
        tilia_errors.assert_no_error()

    def test_preemptive_done_populates_cache_without_swap(self, player, tmp_path):
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        rendered = tmp_path / "0.5x.wav"
        rendered.write_bytes(b"")

        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch("tilia.media.player.qtaudio.render_stretched", return_value=rendered),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
            patch.object(player, "_swap_source") as swap,
        ):
            pool.return_value.start = lambda runnable: runnable.run()
            # User isn't actively asking for any non-unit rate.
            player._pending_rate = 1.0
            player._start_render(0.5, user_initiated=False)

        assert player._rate_cache[("/tmp/song.mp3", 0.5)] == rendered
        swap.assert_not_called()

    def test_user_picks_rate_currently_being_preemptively_rendered(
        self, player, tmp_path
    ):
        # The user picks 0.5x while it's already in-flight as a
        # preemptive render. We shouldn't spawn a second worker — but
        # the user's pick should still cause a swap when the existing
        # one finishes.
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        rendered = tmp_path / "0.5x.wav"
        rendered.write_bytes(b"")

        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch("tilia.media.player.qtaudio.render_stretched", return_value=rendered),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
            patch.object(player, "_swap_source") as swap,
        ):
            captured: list = []
            pool.return_value.start = lambda runnable: captured.append(runnable)

            # First the preemptive (no swap requested).
            player._start_render(0.5, user_initiated=False)
            # Then the user picks it.
            player._engine_try_playback_rate(0.5)
            # Only the preemptive runnable should have been queued.
            assert len(captured) == 1
            # Now let it finish.
            captured[0].run()

        # The completion handler that fires is the *preemptive* one
        # (user_initiated=False) — and since `_pending_rate` is now
        # 0.5, it still swaps. So the user gets their rate without
        # waiting for a duplicate render.
        swap.assert_called_once_with(str(rendered), rate=0.5)


class TestSwapSourceShortCircuit:
    """`_swap_source` skips Qt's async `setSource` when the requested
    path already matches the current source — otherwise `wait_for_signal`
    would hit its 200ms timeout (because `LoadedMedia` doesn't re-fire
    for the same URL) and the function would silently fall through
    without the seek that follows being reliable."""

    def test_swap_to_current_source_does_not_call_setsource(self, player):
        from PySide6.QtCore import QUrl

        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        url = QUrl.fromLocalFile("/tmp/song.mp3")
        with (
            patch.object(player.player, "source", return_value=url),
            patch.object(player.player, "setSource") as set_source,
        ):
            player._swap_source("/tmp/song.mp3", rate=1.0)

        set_source.assert_not_called()


class TestUnloadClearsCache:
    def test_clear_cache_removes_files(self, player, tmp_path):
        a = tmp_path / "a.wav"
        b = tmp_path / "b.wav"
        a.write_bytes(b"")
        b.write_bytes(b"")
        player._rate_cache[("/tmp/song.mp3", 0.5)] = a
        player._rate_cache[("/tmp/song.mp3", 0.75)] = b

        player._clear_cache()

        assert not a.exists()
        assert not b.exists()
        assert player._rate_cache == {}

    def test_clear_cache_swallows_missing_files(self, player, tmp_path):
        ghost = tmp_path / "never-existed.wav"
        player._rate_cache[("/tmp/song.mp3", 0.5)] = ghost

        player._clear_cache()  # must not raise

        assert player._rate_cache == {}


class TestUserWaitCursor:
    """When a user-initiated rate change has no cached file, we push an
    app-wide ``WaitCursor`` so the user can see their pick is being
    processed. The plain status-bar message proved too subtle in
    practice."""

    def test_user_initiated_render_pushes_cursor(self, player):
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance"),
        ):
            player._engine_try_playback_rate(0.5)

        assert player._cursor_pushed is True
        assert player._user_wait_rate == 0.5

    def test_cache_hit_does_not_push_cursor(self, player, tmp_path):
        rendered = tmp_path / "cached.wav"
        rendered.write_bytes(b"")
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        player._rate_cache[("/tmp/song.mp3", 0.5)] = rendered

        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance"),
            patch.object(player, "_swap_source"),
        ):
            player._engine_try_playback_rate(0.5)

        assert player._cursor_pushed is False
        assert player._user_wait_rate is None

    def test_completion_pops_cursor(self, player, tmp_path):
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        rendered = tmp_path / "0.5x.wav"
        rendered.write_bytes(b"")

        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch("tilia.media.player.qtaudio.render_stretched", return_value=rendered),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
            patch.object(player, "_swap_source"),
        ):
            pool.return_value.start = lambda runnable: runnable.run()
            player._engine_try_playback_rate(0.5)

        assert player._cursor_pushed is False
        assert player._user_wait_rate is None

    def test_failure_pops_cursor(self, player, tmp_path, tilia_errors):
        from tilia.media.player.stretch import StretchError

        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)

        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch(
                "tilia.media.player.qtaudio.render_stretched",
                side_effect=StretchError("boom"),
            ),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
            patch.object(player.player, "setPlaybackRate"),
        ):
            pool.return_value.start = lambda runnable: runnable.run()
            player._engine_try_playback_rate(0.5)

        assert player._cursor_pushed is False
        assert player._user_wait_rate is None

    def test_switch_to_cached_rate_mid_render_pops_cursor(self, player, tmp_path):
        # User picks 0.5 (no cache, render starts → cursor pushed),
        # then picks 0.75 which is already cached. The 0.75 path should
        # pop the cursor immediately rather than wait for the orphaned
        # 0.5 render to finish.
        cached_075 = tmp_path / "0.75x.wav"
        cached_075.write_bytes(b"")
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        player._rate_cache[("/tmp/song.mp3", 0.75)] = cached_075

        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
            patch.object(player, "_swap_source"),
        ):
            pool.return_value.start = lambda runnable: None  # never finish
            player._engine_try_playback_rate(0.5)
            assert player._cursor_pushed is True

            player._engine_try_playback_rate(0.75)

        assert player._cursor_pushed is False
        assert player._user_wait_rate is None

    def test_switch_to_rate_one_mid_render_pops_cursor(self, player):
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
            patch.object(player, "_swap_source"),
        ):
            pool.return_value.start = lambda runnable: None
            player._engine_try_playback_rate(0.5)
            assert player._cursor_pushed is True

            player._engine_try_playback_rate(1.0)

        assert player._cursor_pushed is False
        assert player._user_wait_rate is None

    def test_clear_cache_pops_cursor(self, player):
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
        ):
            pool.return_value.start = lambda runnable: None
            player._engine_try_playback_rate(0.5)
            assert player._cursor_pushed is True

            player._clear_cache()

        assert player._cursor_pushed is False
        assert player._user_wait_rate is None

    def test_preemptive_render_does_not_push_cursor(self, player):
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
        ):
            pool.return_value.start = lambda runnable: None
            player._queue_preemptive_renders()

        assert player._cursor_pushed is False
        assert player._user_wait_rate is None

    def test_user_picks_during_preemptive_render_pops_cursor_on_completion(
        self, player, tmp_path
    ):
        # Preemptive render in flight, user picks the same rate before
        # it finishes. The cursor pushes (user is now waiting). When
        # the original preemptive worker completes, its handler should
        # still pop the cursor — the signal was bound with
        # user_initiated=False, but state tracks that the user is now
        # waiting.
        _set_loaded(player, "/tmp/song.mp3", 20.0, rate=1.0)
        rendered = tmp_path / "0.5x.wav"
        rendered.write_bytes(b"")

        with (
            patch("tilia.media.player.qtaudio.is_stretch_available", return_value=True),
            patch("tilia.media.player.qtaudio.render_stretched", return_value=rendered),
            patch("tilia.media.player.qtaudio.QThreadPool.globalInstance") as pool,
            patch.object(player, "_swap_source"),
        ):
            captured: list = []
            pool.return_value.start = lambda runnable: captured.append(runnable)

            player._start_render(0.5, user_initiated=False)
            player._engine_try_playback_rate(0.5)
            assert player._cursor_pushed is True

            captured[0].run()

        assert player._cursor_pushed is False
        assert player._user_wait_rate is None


class TestRubberbandDirection:
    """Regression test: rubberband CLI's ``-T`` is *tempo multiplier*, not
    time ratio. An inverted call (e.g. ``-T 1/rate``) renders a file
    of the wrong duration, which silently breaks the seek-time math
    (and makes 'increase rate' sound like 'decrease rate')."""

    def test_rubberband_invocation_uses_rate_as_tempo(self, tmp_path):
        from pathlib import Path
        from unittest.mock import MagicMock

        from tilia.media.player import stretch

        src = tmp_path / "song.wav"
        src.write_bytes(b"")

        def _run(cmd, *args, **kwargs):
            # `_run_to_partial` writes to cmd[-1] (the .partial sibling),
            # then atomic-renames to the final path; materialise the file
            # so the rename has something to publish.
            Path(cmd[-1]).write_bytes(b"")
            return MagicMock(returncode=0, stderr="")

        # Make the decoded WAV "exist" so the rubberband call goes
        # through to the second subprocess.run.
        with (
            patch.object(stretch, "_decode_to_wav", return_value=src),
            patch.object(
                stretch.shutil,
                "which",
                side_effect=lambda exe: f"/fake/{exe}" if exe == "rubberband" else None,
            ),
            patch.object(stretch, "_cache_dir", return_value=tmp_path),
        ):
            with patch.object(stretch.subprocess, "run", side_effect=_run) as run:
                stretch.render_stretched(str(src), 2.0)

        cmd = run.call_args.args[0]
        assert "--tempo" in cmd
        # The tempo value must be the rate itself, not 1/rate.
        idx = cmd.index("--tempo")
        assert float(cmd[idx + 1]) == 2.0
