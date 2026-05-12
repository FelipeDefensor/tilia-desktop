import os

import pytest

from tests.constants import EXAMPLE_MEDIA_PATH
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


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Tests are flaky on CI.")
class TestPlayer:
    @staticmethod
    def _load_example():
        post(Post.APP_MEDIA_LOAD, EXAMPLE_MEDIA_PATH)

    def test_unload_media(self, tilia):
        self._load_example()
        post(Post.APP_CLEAR)

    def test_unload_media_after_playing(self, tilia):
        self._load_example()
        commands.execute("media.toggle_play", False)
        commands.execute("media.toggle_play", True)
        post(Post.APP_CLEAR)

    def test_unload_media_while_playing(self, tilia):
        self._load_example()
        commands.execute("media.toggle_play", False)
        post(Post.APP_CLEAR)


class TestTogglePlayWithLoop:
    """Pressing Play while a loop is active should preserve the user's
    current position (e.g. from a previous seek) unless they're outside
    the loop range. Previously toggle_play unconditionally seeked to
    loop_start, which made transcription workflows (set whole-song loop,
    pause, click element to seek to a passage, press play) reset to the
    start of the song instead of playing from the passage.
    """

    def test_play_inside_loop_does_not_snap_to_loop_start(self, tilia):
        player = tilia.player
        player.duration = 200.0
        player.playback_end = 200.0
        player.is_looping = True
        player.loop_start = 0.0
        player.loop_end = 200.0
        player.current_time = 150.0
        player.is_playing = False
        player.is_media_loaded = True

        from unittest.mock import patch

        with patch.object(player, "_engine_play"), patch.object(
            player, "_engine_seek"
        ) as engine_seek, patch.object(player, "start_play_loop"):
            player.toggle_play(True)

        # The bug: engine_seek was called with 0.0 (loop_start). With the
        # fix: engine_seek is NOT called, because current_time is inside
        # the loop range.
        engine_seek.assert_not_called()
        assert player.current_time == 150.0

    def test_play_outside_loop_snaps_to_loop_start(self, tilia):
        player = tilia.player
        player.duration = 200.0
        player.playback_end = 200.0
        player.is_looping = True
        player.loop_start = 50.0
        player.loop_end = 150.0
        player.current_time = 180.0  # past loop_end
        player.is_playing = False
        player.is_media_loaded = True

        from unittest.mock import patch

        with patch.object(player, "_engine_play"), patch.object(
            player, "_engine_seek"
        ) as engine_seek, patch.object(player, "start_play_loop"):
            player.toggle_play(True)

        # Outside the loop range, snap to loop_start so playback actually
        # plays the loop instead of running off the end immediately.
        engine_seek.assert_called_once_with(50.0)
        assert player.current_time == 50.0

    def test_play_at_exact_loop_end_does_not_snap(self, tilia):
        # Edge case: current_time exactly at loop_end is still within
        # the loop (the comparison uses <= with a tolerance E). Without
        # the tolerance, a play_loop tick at end-of-loop would re-snap
        # right back to loop_start on the next toggle_play.
        player = tilia.player
        player.duration = 200.0
        player.playback_end = 200.0
        player.is_looping = True
        player.loop_start = 0.0
        player.loop_end = 100.0
        player.current_time = 100.0
        player.is_playing = False
        player.is_media_loaded = True

        from unittest.mock import patch

        with patch.object(player, "_engine_play"), patch.object(
            player, "_engine_seek"
        ) as engine_seek, patch.object(player, "start_play_loop"):
            player.toggle_play(True)

        engine_seek.assert_not_called()

    def test_play_without_loop_is_unaffected(self, tilia):
        player = tilia.player
        player.duration = 200.0
        player.playback_end = 200.0
        player.is_looping = False
        player.current_time = 150.0
        player.is_playing = False
        player.is_media_loaded = True

        from unittest.mock import patch

        with patch.object(player, "_engine_play"), patch.object(
            player, "_engine_seek"
        ) as engine_seek, patch.object(player, "start_play_loop"):
            player.toggle_play(True)

        engine_seek.assert_not_called()
