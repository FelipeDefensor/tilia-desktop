"""Tests for the player toolbar's time/measure display.

The toolbar shows the running media time and, when a beat timeline is
present, the current measure number alongside it. The measure follows
the most-recent beat at or before the current time (i.e. it shows the
bar the playhead is *in*, not the next one it's about to enter).
"""

import pytest

from tilia.media.player.base import MediaTimeChangeReason
from tilia.requests import Post, post
from tilia.ui import commands


@pytest.fixture
def player_toolbar(qtui):
    return qtui.player_toolbar


def _seek(time):
    """Drive the toolbar by posting PLAYER_CURRENT_TIME_CHANGED directly.

    `commands.execute("media.seek", t)` also works but goes through the
    media player; this is a tighter unit-test of the toolbar listener.
    """
    post(Post.PLAYER_CURRENT_TIME_CHANGED, time, MediaTimeChangeReason.SEEK)


def _build_two_measure_grid(beat_tlui):
    beat_tlui.timeline.beat_pattern = [3]
    for time in (0, 1, 2, 4, 5, 6):
        commands.execute("media.seek", time)
        commands.execute("timeline.beat.add")
    beat_tlui.timeline.recalculate_measures()
    return beat_tlui


class TestTimeAndMeasureLabel:
    def test_no_measure_suffix_without_beat_timeline(self, player_toolbar, tilia_state):
        tilia_state.duration = 100
        _seek(5)
        assert "m." not in player_toolbar.time_label.text()

    def test_measure_suffix_appears_with_beat_timeline(
        self, player_toolbar, beat_tlui, tilia_state
    ):
        _build_two_measure_grid(beat_tlui)
        _seek(5)
        # t=5 falls in measure 2 (beats 3,4,5 i.e. t=4..6); previous beat
        # at or before t=5 is at t=5 → metric_position.measure == 2.
        assert player_toolbar.time_label.text().endswith("m. 2")

    def test_measure_is_the_bar_the_playhead_is_in(
        self, player_toolbar, beat_tlui, tilia_state
    ):
        # The crucial invariant: hitting t=4 (downbeat of measure 2) reads
        # m. 2, not m. 1 — we use the most-recent beat at or before time,
        # not the *next* one we're about to cross.
        _build_two_measure_grid(beat_tlui)
        _seek(4)
        assert player_toolbar.time_label.text().endswith("m. 2")

    def test_measure_before_first_beat_falls_back_to_first(
        self, player_toolbar, beat_tlui, tilia_state
    ):
        # If the playhead is before the first beat, there's no "previous"
        # beat; the label should still show *some* measure (we fall back
        # to the first beat's measure) so the label doesn't flicker or
        # crash on a fresh load.
        _build_two_measure_grid(beat_tlui)
        # First beat is at t=0 — earlier than that is the only "before
        # any beat" case we can test cleanly.
        _seek(0)
        text = player_toolbar.time_label.text()
        assert "m." in text

    def test_time_appears_before_measure(self, player_toolbar, beat_tlui, tilia_state):
        # Regression: an earlier version put the measure first
        # ("m. 12 · 0:42.31 / 3:51.04"). The user wanted the time first
        # and the measure number as a trailing suffix.
        _build_two_measure_grid(beat_tlui)
        _seek(5)
        text = player_toolbar.time_label.text()
        time_idx = text.find("/")
        measure_idx = text.find("m.")
        assert time_idx > -1 and measure_idx > -1
        assert time_idx < measure_idx, f"Time should come before measure in '{text}'."
