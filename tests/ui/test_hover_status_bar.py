"""Tests for the status-bar hover label.

The QtUI adds a permanent QLabel to the right side of the main window's
status bar. As the user moves the cursor across any timeline,
`Post.TIMELINE_VIEW_HOVER` fires with the cursor's x; the label
displays the corresponding media time (and, if a beat timeline exists,
the measure number). Leaving the timeline area posts None and clears
the label.
"""

import pytest

from tilia.requests import Post, post
from tilia.ui import commands
from tilia.ui.coords import time_x_converter


@pytest.fixture
def hover_label(qtui):
    return qtui.hover_label


def _hover_x(x):
    post(Post.TIMELINE_VIEW_HOVER, x)


def _hover_clear():
    post(Post.TIMELINE_VIEW_HOVER, None)


def _build_two_measure_grid(beat_tlui):
    beat_tlui.timeline.beat_pattern = [3]
    for time in (0, 1, 2, 4, 5, 6):
        commands.execute("media.seek", time)
        commands.execute("timeline.beat.add")
    beat_tlui.timeline.recalculate_measures()
    return beat_tlui


class TestHoverLabel:
    def test_shows_time_at_cursor(self, hover_label, tilia_state):
        # Just time, no beat timeline yet.
        _hover_x(time_x_converter.get_x_by_time(5))
        text = hover_label.text()
        assert "m." not in text
        # The exact format comes from `format_media_time`; check the
        # parts that matter rather than the literal string.
        assert text  # non-empty
        assert ":" in text  # mm:ss

    def test_shows_measure_when_beat_timeline_exists(
        self, hover_label, beat_tlui, tilia_state
    ):
        _build_two_measure_grid(beat_tlui)
        _hover_x(time_x_converter.get_x_by_time(5))
        text = hover_label.text()
        assert text.endswith("m. 2"), text

    def test_clears_on_hover_leave(self, hover_label, tilia_state):
        _hover_x(time_x_converter.get_x_by_time(5))
        assert hover_label.text()

        _hover_clear()
        assert hover_label.text() == ""

    def test_clears_when_hover_is_outside_playback_area(self, hover_label, tilia_state):
        # Hovering over the label margin (x < left_margin) maps to a
        # negative time; the label should clear rather than show
        # "-0:00.5".
        _hover_x(0)  # x=0 is in the label margin
        assert hover_label.text() == ""
