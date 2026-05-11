"""Tests for the Ctrl+K seek-to-measure dialog.

The dialog asks the user for a measure number or a relative motion like
"+3" / "-2" and then seeks the player to the corresponding beat time.

The dialog itself is a `QInputDialog.getText` modal, which can't be
driven from a test, so we patch the static method and let the rest of
the flow run.
"""

from unittest.mock import patch

import pytest

from tilia.ui import commands


@pytest.fixture
def beats_in_two_measures(beat_tlui):
    beat_tlui.timeline.beat_pattern = [3]
    for time in (0, 1, 2, 4, 5, 6):
        commands.execute("media.seek", time)
        commands.execute("timeline.beat.add")
    beat_tlui.timeline.recalculate_measures()
    return beat_tlui


def _trigger_seek_to_measure(tluis, input_text: str) -> None:
    with patch(
        "tilia.ui.timelines.collection.collection.QInputDialog.getText",
        return_value=(input_text, True),
    ):
        tluis.on_seek_to_measure()


class TestSeekToMeasure:
    def test_seek_by_absolute_measure(self, tluis, beats_in_two_measures, tilia_state):
        _trigger_seek_to_measure(tluis, "2")

        # Measure 2 starts at beat index 3 (t=4).
        assert tilia_state.player.current_time == 4

    def test_seek_by_relative_motion(self, tluis, beats_in_two_measures, tilia_state):
        # Place the playhead between two beats.
        commands.execute("media.seek", 4.5)

        _trigger_seek_to_measure(tluis, "+1")

        # +1 beat from the closest beat (t=4) → t=5.
        assert tilia_state.player.current_time == 5

    def test_error_when_no_beat_timeline(self, tluis, tilia_errors):
        _trigger_seek_to_measure(tluis, "1")

        tilia_errors.assert_error()
        tilia_errors.assert_in_error_title("Seek")

    def test_finds_beat_timeline_with_any_name(
        self, tluis, beats_in_two_measures, tilia_state
    ):
        # Regression: the seek code used to require a timeline literally
        # named "Measures". Make sure renaming the timeline doesn't break
        # the lookup.
        beats_in_two_measures.timeline.set_data("name", "Battute")

        _trigger_seek_to_measure(tluis, "2")

        assert tilia_state.player.current_time == 4
