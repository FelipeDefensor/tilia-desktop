import os
import sys
import time
from unittest.mock import patch

import pytest
import shiboken6
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.constants import EXAMPLE_MEDIA_PATH
from tests.mock import Serve
from tests.utils import EXAMPLE_VIDEO_FILENAME, load_local_media
from tilia.requests import Get, Post, get, listen, post, stop_listening
from tilia.ui import commands
from tilia.ui.coords import time_x_converter
from tilia.ui.format import format_media_time


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


@pytest.fixture
def uncaught(monkeypatch):
    # Qt hands exceptions raised in its slots (like the play loop's timer)
    # to sys.excepthook, where the app shows its crash dialog and exits.
    # They never reach pytest, so collect them here.
    exceptions = []
    monkeypatch.setattr(sys, "excepthook", lambda *info: exceptions.append(info[1]))
    return exceptions


@pytest.fixture(autouse=True)
def stop_playback_at_end(tilia):
    yield
    tilia.player.stop()
    # Unloading media while it plays leaves the play loop running (see
    # TestNewFile), and it raises once media of another kind replaces the
    # player.
    tilia.player.stop_play_loop()


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
    def paths(self, resources):
        # A file of each kind to load first, and a different one to load
        # over it.
        def path(name):
            return str((resources / name).resolve())

        return {
            "audio": (EXAMPLE_MEDIA_PATH, path("example.wav")),
            "video": (path(EXAMPLE_VIDEO_FILENAME), path("example2.mp4")),
        }

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


@pytest.fixture
def media_paths(resources):
    # A file of each kind to play. The video has sound too.
    return {
        "audio": EXAMPLE_MEDIA_PATH,
        "video": str((resources / "example2.mp4").resolve()),
    }


@pytest.fixture
def reported_times():
    # The times the player reports to the rest of the app (the time label,
    # the timelines), each with the clock time it was reported at.
    reports = []

    def on_time_changed(media_time, *_):
        reports.append((time.monotonic(), media_time))

    listen(on_time_changed, Post.PLAYER_CURRENT_TIME_CHANGED, on_time_changed)
    yield reports
    stop_listening(on_time_changed, Post.PLAYER_CURRENT_TIME_CHANGED)


def load_muted(tilia, path):
    load_local_media(path)
    tilia.player.audio_output.setMuted(True)  # a new player isn't muted


def start_playback(tilia, qtui):
    qtui.player_toolbar.play_toggle_action.trigger()
    assert process_events_until(
        lambda: tilia.player.current_time > 0
    ), "the media didn't play"


def shown_time(qtui):
    # The current time on the player toolbar's time label.
    return qtui.player_toolbar.time_label.text().split("/")[0]


def slider_time(slider_tlui):
    # The time where the slider timeline's trough is.
    x = slider_tlui.trough.sceneBoundingRect().center().x()
    return time_x_converter.get_time_by_x(x)


def assert_plays_on_from(tilia, qtui, reported_times, start):
    assert tilia.player.current_time == pytest.approx(start)
    reported_times.clear()
    assert process_events_until(lambda: tilia.player.current_time > start + 0.2)
    # Playback from anywhere before start would report earlier times.
    assert min(t for _, t in reported_times) > start - 0.05
    assert tilia.player.is_playing
    assert qtui.player_toolbar.play_toggle_action.isChecked()
    assert shown_time(qtui) == format_media_time(tilia.player.current_time)


class TestPlayerToolbar:
    # Plays real media, muted, with the controls on the player toolbar.

    def test_play_starts_from_the_start(self, tilia, qtui, slider_tlui, uncaught):
        load_muted(tilia, EXAMPLE_MEDIA_PATH)
        play = qtui.player_toolbar.play_toggle_action

        pressed_at = time.monotonic()
        play.trigger()

        assert play.isChecked()
        assert process_events_until(lambda: tilia.player.current_time > 0.2)
        assert tilia.player.is_playing
        # Media played from anywhere but the start would be ahead of the clock.
        assert tilia.player.current_time < time.monotonic() - pressed_at + 0.25
        assert shown_time(qtui) == format_media_time(tilia.player.current_time)
        assert slider_time(slider_tlui) == pytest.approx(tilia.player.current_time)
        assert uncaught == []

    def test_pausing_stops_the_time(self, tilia, qtui, slider_tlui, uncaught):
        load_muted(tilia, EXAMPLE_MEDIA_PATH)
        start_playback(tilia, qtui)
        play = qtui.player_toolbar.play_toggle_action
        engine = tilia.player.player

        play.trigger()

        assert not play.isChecked()
        assert not tilia.player.is_playing
        paused_at = tilia.player.current_time
        engine_position = engine.position()
        process_events_for(0.3)  # long enough for the time to advance, if it did
        assert tilia.player.current_time == paused_at
        assert engine.position() == pytest.approx(engine_position, abs=50)  # ms
        assert shown_time(qtui) == format_media_time(paused_at)
        assert slider_time(slider_tlui) == pytest.approx(paused_at)
        assert uncaught == []

    def test_play_resumes_paused_media_where_it_was_paused(
        self, tilia, qtui, slider_tlui, reported_times, uncaught
    ):
        load_muted(tilia, EXAMPLE_MEDIA_PATH)
        start_playback(tilia, qtui)
        play = qtui.player_toolbar.play_toggle_action
        # Far enough from the start to tell them apart.
        assert process_events_until(lambda: tilia.player.current_time > 0.5)
        play.trigger()
        paused_at = tilia.player.current_time

        play.trigger()

        assert_plays_on_from(tilia, qtui, reported_times, paused_at)
        assert slider_time(slider_tlui) == pytest.approx(tilia.player.current_time)
        assert uncaught == []

    def test_stopping_while_playing_goes_back_to_the_start(
        self, tilia, qtui, slider_tlui, uncaught
    ):
        load_muted(tilia, EXAMPLE_MEDIA_PATH)
        start_playback(tilia, qtui)
        toolbar = qtui.player_toolbar

        toolbar.stop_action.trigger()

        assert not tilia.player.is_playing
        assert not toolbar.play_toggle_action.isChecked()
        process_events_for(0.3)  # long enough for the time to advance, if it did
        assert tilia.player.current_time == 0
        assert tilia.player.player.position() == 0
        assert shown_time(qtui) == "00:00.0"
        assert slider_time(slider_tlui) == pytest.approx(0)
        assert uncaught == []

    @pytest.mark.parametrize("kind", ["audio", "video"])
    def test_playback_rate_spinbox_changes_the_speed(
        self, tilia, qtui, media_paths, reported_times, uncaught, kind
    ):
        load_muted(tilia, media_paths[kind])
        start_playback(tilia, qtui)
        reported_times.clear()

        qtui.player_toolbar.playback_rate_spinbox.setValue(2)

        assert tilia.player.player.playbackRate() == 2
        assert process_events_until(lambda: len(reported_times) > 8)
        (start_clock, start), *_, (end_clock, end) = reported_times
        # Seconds of media played per second of the clock.
        assert (end - start) / (end_clock - start_clock) == pytest.approx(2, abs=0.4)
        assert uncaught == []

    def test_volume_slider_sets_the_volume(self, tilia, qtui, uncaught):
        load_muted(tilia, EXAMPLE_MEDIA_PATH)
        start_playback(tilia, qtui)
        slider = qtui.player_toolbar.volume_slider
        output = tilia.player.audio_output

        slider.setValue(50)
        half = output.volume()
        slider.setValue(0)
        silent = output.volume()
        slider.setValue(100)
        full = output.volume()

        assert silent == 0 < half < full
        assert uncaught == []

    def test_mute_button_mutes_and_unmutes(self, tilia, qtui, uncaught):
        load_muted(tilia, EXAMPLE_MEDIA_PATH)
        start_playback(tilia, qtui)
        toolbar = qtui.player_toolbar
        output = tilia.player.audio_output
        toolbar.volume_slider.setValue(0)  # so that it plays nothing unmuted either
        output.setMuted(False)

        toolbar.volume_toggle_action.trigger()

        assert output.isMuted()
        assert not toolbar.volume_slider.isEnabled()

        toolbar.volume_toggle_action.trigger()

        assert not output.isMuted()
        assert toolbar.volume_slider.isEnabled()
        assert uncaught == []


class TestSeekWithMouse:
    # Seeks with real mouse events, ahead of where real media plays, muted. A
    # single click doesn't seek while media plays, by design, so these drag
    # or double-click.

    def test_dragging_the_slider_seeks_while_playing(
        self, tilia, qtui, slider_tlui, reported_times, uncaught
    ):
        load_muted(tilia, EXAMPLE_MEDIA_PATH)
        start_playback(tilia, qtui)
        view = slider_tlui.view
        trough = view.mapFromScene(slider_tlui.trough.sceneBoundingRect().center())
        target = QPoint(round(time_x_converter.get_x_by_time(6)), trough.y())

        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=trough)
        QTest.mouseMove(view.viewport(), target)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=target)

        assert_plays_on_from(
            tilia, qtui, reported_times, time_x_converter.get_time_by_x(target.x())
        )
        assert slider_time(slider_tlui) == pytest.approx(tilia.player.current_time)
        assert uncaught == []

    def test_double_clicking_the_slider_seeks_while_playing(
        self, tilia, qtui, slider_tlui, reported_times, uncaught
    ):
        load_muted(tilia, EXAMPLE_MEDIA_PATH)
        start_playback(tilia, qtui)
        view = slider_tlui.view
        point = QPoint(round(time_x_converter.get_x_by_time(6)), view.height() // 2)

        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)

        assert_plays_on_from(
            tilia, qtui, reported_times, time_x_converter.get_time_by_x(point.x())
        )
        assert slider_time(slider_tlui) == pytest.approx(tilia.player.current_time)
        assert uncaught == []

    def test_double_clicking_a_hierarchy_seeks_to_its_start_while_playing(
        self, tilia, qtui, tluis, reported_times, uncaught
    ):
        load_muted(tilia, EXAMPLE_MEDIA_PATH)
        commands.execute("timelines.add.hierarchy", name="")
        commands.execute("timeline.hierarchy.split", time=6)
        hierarchy_tlui = tluis[0]
        start_playback(tilia, qtui)
        view = hierarchy_tlui.view
        body = hierarchy_tlui[1].body  # of the unit from 6s to the end
        point = view.mapFromScene(
            QPointF(
                time_x_converter.get_x_by_time(7),
                body.sceneBoundingRect().center().y(),
            )
        )

        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)

        assert_plays_on_from(tilia, qtui, reported_times, 6)
        assert hierarchy_tlui.playback_line.line().x1() == pytest.approx(
            time_x_converter.get_x_by_time(tilia.player.current_time)
        )
        assert uncaught == []


class TestEndOfPlayback:
    # Plays real media, muted, from close to its end.

    @pytest.mark.parametrize("kind", ["audio", "video"])
    def test_playback_stops_at_the_end(
        self,
        tilia,
        qtui,
        slider_tlui,
        media_paths,
        reported_times,
        tilia_errors,
        uncaught,
        kind,
    ):
        load_muted(tilia, media_paths[kind])
        commands.execute("media.seek", tilia.player.duration - 0.5)
        play = qtui.player_toolbar.play_toggle_action

        play.trigger()

        assert process_events_until(lambda: not tilia.player.is_playing)
        assert max(t for _, t in reported_times) == pytest.approx(
            tilia.player.duration, abs=0.15
        ), "playback stopped before the end"
        process_events_for(0.3)  # long enough for the time to advance, if it did
        assert not tilia.player.is_playing
        assert tilia.player.current_time == 0
        assert not play.isChecked()
        assert shown_time(qtui) == "00:00.0"
        assert slider_time(slider_tlui) == pytest.approx(0)
        assert uncaught == []
        tilia_errors.assert_no_error()


class TestNewFile:
    # File > New while audio plays, answering "don't save". An old report
    # says this froze.

    @pytest.fixture
    def playing_audio(self, tilia, qtui):
        load_muted(tilia, EXAMPLE_MEDIA_PATH)
        start_playback(tilia, qtui)
        player = tilia.player
        yield
        # File > New leaves its play loop running, also once video replaces
        # it, where stop_playback_at_end doesn't reach.
        player.stop_play_loop()

    @staticmethod
    def new_file():
        with Serve(Get.FROM_USER_SHOULD_SAVE_CHANGES, (True, False)):
            commands.execute("file.new")

    def test_new_file_while_playing_stops_and_unloads_the_media(
        self, tilia, qtui, tilia_errors, uncaught, playing_audio
    ):
        self.new_file()

        process_events_for(0.3)  # several ticks of a play loop left running
        assert not tilia.player.is_playing
        assert tilia.player.player.playbackState() == (
            QMediaPlayer.PlaybackState.StoppedState
        )
        assert get(Get.MEDIA_PATH) == ""
        assert not qtui.player_toolbar.isEnabled()
        assert shown_time(qtui) == "00:00.0"
        assert uncaught == []
        tilia_errors.assert_no_error()

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Player.unload_media, which File > New runs, doesn't post"
            " PLAYER_STOPPED, so the player toolbar's play button stays checked."
        ),
    )
    def test_new_file_while_playing_unchecks_the_play_button(self, qtui, playing_audio):
        self.new_file()

        assert not qtui.player_toolbar.play_toggle_action.isChecked()

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Player.unload_media, which File > New runs, doesn't stop the play"
            " loop. Once video replaces the audio player, the loop polls that"
            " player, whose engine is gone, and raises AttributeError, which"
            " shows the crash dialog."
        ),
    )
    def test_loading_video_after_new_file_while_playing_raises_nothing(
        self, media_paths, uncaught, playing_audio
    ):
        self.new_file()

        load_local_media(media_paths["video"])
        process_events_for(0.3)  # several ticks of a play loop left running

        assert uncaught == []
