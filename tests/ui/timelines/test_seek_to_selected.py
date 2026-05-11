"""Tests for the Ctrl+J seek-to-selected-element shortcut.

When the user has one or more elements selected across any timeline,
Ctrl+J seeks the player to the start of the earliest one. This is
intended for transcription work where the user wants to replay a
selected passage without manually scrubbing.

The shortcut is silent when nothing is selected (rather than erroring)
so it can be pressed safely as a habit.
"""

import pytest

from tilia.ui import commands


@pytest.fixture
def with_duration(tilia_state):
    tilia_state.duration = 100
    return tilia_state


class TestSeekToSelectedElement:
    def test_seek_to_hierarchy_start(self, tluis, hierarchy_tlui, with_duration):
        hierarchy_tlui.create_hierarchy(7, 10, 1)
        hierarchy_tlui.select_element(hierarchy_tlui[0])

        tluis.on_seek_to_selected_element()

        assert with_duration.current_time == 7

    def test_seek_to_range_start(self, tluis, range_tlui, with_duration):
        commands.execute("timeline.range.add_range", start=12, end=18)
        range_tlui.select_element(range_tlui[0])

        tluis.on_seek_to_selected_element()

        assert with_duration.current_time == 12

    def test_seek_to_marker_time(self, tluis, marker_tlui, with_duration):
        marker_tlui.create_marker(20)
        marker_tlui.select_element(marker_tlui[0])

        tluis.on_seek_to_selected_element()

        assert with_duration.current_time == 20

    def test_seek_picks_earliest_among_multiple_selections(
        self, tluis, hierarchy_tlui, marker_tlui, with_duration
    ):
        # A range at t=30 and a marker at t=5; Ctrl+J should jump back
        # to the earlier one — that's the transcription replay use-case.
        hierarchy_tlui.create_hierarchy(30, 40, 1)
        marker_tlui.create_marker(5)
        hierarchy_tlui.select_element(hierarchy_tlui[0])
        marker_tlui.select_element(marker_tlui[0])

        tluis.on_seek_to_selected_element()

        assert with_duration.current_time == 5

    def test_no_selection_is_a_noop(self, tluis, hierarchy_tlui, with_duration):
        # Create something but don't select it.
        hierarchy_tlui.create_hierarchy(7, 10, 1)
        commands.execute("media.seek", 42)

        tluis.on_seek_to_selected_element()

        # Player stays put.
        assert with_duration.current_time == 42

    def test_clamps_to_media_start(self, tluis, hierarchy_tlui, with_duration):
        # If somehow an element has a negative start (e.g. corrupted load),
        # we still don't want to send a negative seek to the player.
        hierarchy_tlui.create_hierarchy(0, 5, 1)
        hierarchy_tlui.select_element(hierarchy_tlui[0])

        tluis.on_seek_to_selected_element()

        assert with_duration.current_time == 0
