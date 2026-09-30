import os
import sys
import time
from unittest.mock import patch

import pytest
import shiboken6
from PySide6.QtWidgets import QApplication

from tests.constants import EXAMPLE_MEDIA_PATH
from tests.utils import EXAMPLE_VIDEO_FILENAME, load_local_media
from tilia.requests import Post, post
from tilia.ui import commands


@pytest.fixture
def conservative_player_stop(tilia):
    """
    Increases player.SLEEP_AFTER_STOP to 5 seconds if on CI.
    Avoids freezes when setting URL after stop. Workaround for running tests on CI.
    Proper handling of player status changes would be a more robust solution.
    """

    original_sleep_after_stop = tilia.player.SLEEP_AFTER_STOP
    if os.getenv("CI") == "true":
        tilia.player.SLEEP_AFTER_STOP = 5
    yield
    tilia.player.SLEEP_AFTER_STOP = original_sleep_after_stop


def load_example():
    post(Post.APP_MEDIA_LOAD, EXAMPLE_MEDIA_PATH)


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Tests are flaky on CI.")
class TestPlayer:
    def test_unload_media(self, tilia):
        load_example()
        post(Post.APP_CLEAR)

    def test_unload_media_after_playing(self, tilia):
        load_example()
        commands.execute("media.toggle_play", False)
        commands.execute("media.toggle_play", True)
        post(Post.APP_CLEAR)

    def test_unload_media_while_playing(self, tilia):
        load_example()
        commands.execute("media.toggle_play", False)
        post(Post.APP_CLEAR)

    @pytest.mark.skip(
        reason=(
            "Passes on its own, but in a parallel full-suite run the "
            "xdist worker died with a Windows heap-corruption error "
            "(0xc0000374) inside the Qt media engine while changing the rate. "
            "Skipped until that is understood."
        )
    )
    def test_change_playback_rate_with_audio_loaded(self, tilia, qtui):
        # Turning the playback-rate spinbox on the player toolbar
        # while audio is loaded must change the player's actual rate.
        load_example()

        qtui.player_toolbar.playback_rate_spinbox.setValue(1.5)

        assert tilia.player.player.playbackRate() == 1.5


class TestStop:
    # Unlike the tests above, these never start playback: they only load
    # media and stop it, so they don't hit the engine timing that makes the
    # rest of this module flaky on CI, and they run there.

    def test_stop_while_paused_resets_to_start(self, tilia):
        # Stopping while paused (i.e. not playing, but not at the
        # start either) must bring the current time back to the start and
        # leave playback stopped.
        load_example()
        tilia.player.current_time = 5.0

        commands.get_qaction("media.stop").trigger()

        assert tilia.player.current_time == 0
        assert not tilia.player.is_playing

    def test_stop_while_stopped_changes_nothing(self, tilia):
        # Stopping while already stopped (current_time == 0, not
        # playing) must be a no-op. Player.stop (tilia/media/player/base.py)
        # early-returns before touching the engine in that case.
        load_example()

        with patch.object(tilia.player, "_engine_stop") as mock_engine_stop:
            commands.get_qaction("media.stop").trigger()

        mock_engine_stop.assert_not_called()
        assert tilia.player.current_time == 0
        assert not tilia.player.is_playing


def process_events_for(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def process_events_until(condition, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while not condition() and time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    return condition()


KEEPS_TIME_OF_PAUSED_MEDIA = pytest.mark.xfail(
    strict=True,
    reason=(
        "Player.on_media_load_done doesn't reset current_time, so media loaded"
        " over paused media of its own kind, which keeps the player, starts"
        " with the paused media's time."
    ),
)


def load_cases():
    """Local audio or video, loaded over nothing, or over audio or video that
    is stopped (loaded and never played), playing or paused."""
    for kind in ("audio", "video"):
        yield pytest.param(kind, None, None, id=f"{kind}-over-nothing")
        for before in ("audio", "video"):
            for state in ("stopped", "playing", "paused"):
                marks = []
                if (before, state) == (kind, "paused"):
                    marks.append(KEEPS_TIME_OF_PAUSED_MEDIA)
                yield pytest.param(
                    kind, before, state, id=f"{kind}-over-{state}-{before}", marks=marks
                )


class TestLoadLocalMedia:
    # Loads local audio or video over nothing, or over audio or video that is
    # stopped, playing or paused, then plays what it loaded. Media of the
    # other kind replaces the player. These play real media, muted.

    @pytest.fixture
    def uncaught(self, monkeypatch):
        # Qt hands exceptions raised in its slots (like the play loop's timer)
        # to sys.excepthook, where the app shows its crash dialog and exits.
        # They never reach pytest, so collect them here.
        exceptions = []
        monkeypatch.setattr(sys, "excepthook", lambda *info: exceptions.append(info[1]))
        return exceptions

    @pytest.fixture
    def paths(self, resources):
        # A file of each kind to load first, and a different one to load
        # over it.
        def path(name):
            return str((resources / name).resolve())

        return {
            "audio": (EXAMPLE_MEDIA_PATH, path("example.wav")),
            "video": (path(EXAMPLE_VIDEO_FILENAME), path("example2.mp4")),
        }

    @pytest.fixture(autouse=True)
    def stop_playback_at_end(self, tilia):
        yield
        tilia.player.stop()

    @pytest.mark.parametrize("kind,before,state", list(load_cases()))
    def test_new_media_loads_and_plays(
        self, tilia, qtui, tilia_errors, paths, uncaught, kind, before, state
    ):
        play = qtui.player_toolbar.play_toggle_action
        if before:
            load_local_media(paths[before][0])
            tilia.player.audio_output.setMuted(True)
            if state in ("playing", "paused"):
                play.trigger()
                assert process_events_until(
                    lambda: tilia.player.current_time > 0
                ), "the first media didn't play"
            if state == "paused":
                play.trigger()
        video_window_before = getattr(tilia.player, "widget", None)

        load_local_media(paths[kind][1])
        process_events_for(0.3)  # several ticks of any play loop left running

        assert uncaught == []
        tilia_errors.assert_no_error()
        assert tilia.player.MEDIA_TYPE == kind
        assert tilia.player.media_path == paths[kind][1]
        # Video shows in a window, which goes away when audio replaces it.
        if kind == "video":
            assert tilia.player.widget.isVisible()
        elif video_window_before is not None:
            assert not shiboken6.isValid(video_window_before)
        assert not tilia.player.is_playing
        assert not play.isChecked()
        assert tilia.player.current_time == 0

        tilia.player.audio_output.setMuted(True)  # a new player isn't muted
        play.trigger()

        assert process_events_until(
            lambda: tilia.player.current_time > 0
        ), "the new media didn't play"
        assert tilia.player.is_playing
        assert uncaught == []
