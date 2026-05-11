"""Tests for the Ctrl+K flexible seek dialog.

The dialog accepts:
    - Plain integer            → absolute measure (legacy behaviour)
    - "Ns" / "Nb" / "Nm"       → absolute seconds / beats / measures
    - "+N" / "-N"              → relative motion in *beats* (legacy)
    - "+Nu" / "-Nu" (u in smb) → relative motion in the chosen unit

It also clamps the resulting time to ``[0, MEDIA_DURATION]`` so that
out-of-range values stop the playhead at the media boundary instead of
silently wrapping (negative) or no-opping (past the end).

The dialog itself is a `QInputDialog.getText` modal, which can't be
driven from a test, so we patch the static method and let the rest of
the flow run.
"""

from unittest.mock import patch

import pytest

from tilia.ui import commands
from tilia.ui.timelines.collection.collection import _parse_seek_input


@pytest.fixture
def beats_in_two_measures(beat_tlui):
    beat_tlui.timeline.beat_pattern = [3]
    for time in (0, 1, 2, 4, 5, 6):
        commands.execute("media.seek", time)
        commands.execute("timeline.beat.add")
    beat_tlui.timeline.recalculate_measures()
    return beat_tlui


def _trigger_seek(tluis, input_text: str) -> None:
    with patch(
        "tilia.ui.timelines.collection.collection.QInputDialog.getText",
        return_value=(input_text, True),
    ):
        tluis.on_seek_to_measure()


class TestSeekParser:
    """Direct unit tests for the dialog input parser."""

    def test_bare_integer_is_absolute_measure(self):
        assert _parse_seek_input("12") == (False, "m", 12.0)

    def test_bare_signed_is_relative_beat(self):
        # Legacy behaviour: "+1" / "-1" with no suffix means +/- 1 beat,
        # not 1 measure. Preserved so users who already know the old
        # dialog don't get surprised.
        assert _parse_seek_input("+3") == (True, "b", 3.0)
        assert _parse_seek_input("-3") == (True, "b", -3.0)

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("30s", (False, "s", 30.0)),
            ("4b", (False, "b", 4.0)),
            ("12m", (False, "m", 12.0)),
            ("+15s", (True, "s", 15.0)),
            ("-2m", (True, "m", -2.0)),
            ("+4b", (True, "b", 4.0)),
        ],
    )
    def test_explicit_units(self, text, expected):
        assert _parse_seek_input(text) == expected

    def test_decimal_seconds(self):
        assert _parse_seek_input("5.5s") == (False, "s", 5.5)
        assert _parse_seek_input("-2.25s") == (True, "s", -2.25)

    def test_whitespace_is_stripped(self):
        assert _parse_seek_input("  5m  ") == (False, "m", 5.0)

    @pytest.mark.parametrize("text", ["", "   ", "abc", "+", "-", "5x", "+m"])
    def test_unparseable_returns_none(self, text):
        assert _parse_seek_input(text) is None


class TestSeekAbsolute:
    def test_absolute_measure_legacy(self, tluis, beats_in_two_measures, tilia_state):
        _trigger_seek(tluis, "2")
        # Measure 2 starts at beat index 3 (t=4).
        assert tilia_state.player.current_time == 4

    def test_absolute_measure_explicit(self, tluis, beats_in_two_measures, tilia_state):
        _trigger_seek(tluis, "2m")
        assert tilia_state.player.current_time == 4

    def test_absolute_beat(self, tluis, beats_in_two_measures, tilia_state):
        # 1-indexed: beat 4 is the first beat of measure 2 (t=4).
        _trigger_seek(tluis, "4b")
        assert tilia_state.player.current_time == 4

    def test_absolute_seconds(self, tluis, beats_in_two_measures, tilia_state):
        _trigger_seek(tluis, "5s")
        assert tilia_state.player.current_time == 5

    def test_absolute_seconds_no_beat_timeline_works(self, tluis, tilia_state):
        # Seconds shouldn't require a beat timeline — make sure the
        # SEEK_NO_BEAT_TIMELINE early return doesn't fire for "s" units.
        _trigger_seek(tluis, "10s")
        assert tilia_state.player.current_time == 10


class TestSeekRelative:
    def test_relative_bare_is_beat(self, tluis, beats_in_two_measures, tilia_state):
        # Legacy: "+1" without a suffix is +1 beat.
        commands.execute("media.seek", 4.5)
        _trigger_seek(tluis, "+1")
        # Closest beat to 4.5 is t=4 → +1 beat → t=5.
        assert tilia_state.player.current_time == 5

    def test_relative_beat_explicit(self, tluis, beats_in_two_measures, tilia_state):
        commands.execute("media.seek", 4)
        _trigger_seek(tluis, "+2b")
        # From t=4 (beat 3, 0-indexed) +2 beats → beat 5 (0-indexed) at t=6.
        assert tilia_state.player.current_time == 6

    def test_relative_measure_forward(self, tluis, beats_in_two_measures, tilia_state):
        commands.execute("media.seek", 0)  # measure 1
        _trigger_seek(tluis, "+1m")
        # +1 measure → measure 2 starts at t=4.
        assert tilia_state.player.current_time == 4

    def test_relative_measure_backward(self, tluis, beats_in_two_measures, tilia_state):
        commands.execute("media.seek", 5)  # mid-measure 2
        _trigger_seek(tluis, "-1m")
        # -1 measure → start of measure 1 (t=0).
        assert tilia_state.player.current_time == 0

    def test_relative_seconds_forward(self, tluis, tilia_state):
        commands.execute("media.seek", 10)
        _trigger_seek(tluis, "+5s")
        assert tilia_state.player.current_time == 15

    def test_relative_seconds_backward(self, tluis, tilia_state):
        commands.execute("media.seek", 10)
        _trigger_seek(tluis, "-3s")
        assert tilia_state.player.current_time == 7


class TestSeekClampsToMediaBounds:
    """Out-of-range seek values clamp to [0, duration] rather than
    wrapping around (negative) or no-opping (past the end)."""

    def test_relative_seconds_before_start_clamps_to_zero(self, tluis, tilia_state):
        commands.execute("media.seek", 5)
        _trigger_seek(tluis, "-100s")
        assert tilia_state.player.current_time == 0

    def test_relative_seconds_past_end_clamps_to_duration(self, tluis, tilia_state):
        commands.execute("media.seek", 5)
        _trigger_seek(tluis, "+1000s")
        # Default duration is 100; the player rounds to ints so the
        # comparison is direct.
        assert tilia_state.player.current_time == tilia_state.duration

    def test_absolute_seconds_negative_clamps_to_zero(self, tluis, tilia_state):
        _trigger_seek(tluis, "-50s")
        assert tilia_state.player.current_time == 0

    def test_absolute_seconds_past_end_clamps(self, tluis, tilia_state):
        _trigger_seek(tluis, "9999s")
        assert tilia_state.player.current_time == tilia_state.duration

    def test_relative_beat_past_end_clamps_to_last_beat(
        self, tluis, beats_in_two_measures, tilia_state
    ):
        # 6 beats; from t=0 (beat 1) "+50b" should land at the last beat,
        # not raise IndexError or wrap.
        commands.execute("media.seek", 0)
        _trigger_seek(tluis, "+50b")
        assert tilia_state.player.current_time == 6  # last beat in fixture

    def test_relative_beat_before_start_clamps_to_first_beat(
        self, tluis, beats_in_two_measures, tilia_state
    ):
        commands.execute("media.seek", 6)  # last beat
        _trigger_seek(tluis, "-99b")
        assert tilia_state.player.current_time == 0

    def test_relative_measure_past_end_clamps(
        self, tluis, beats_in_two_measures, tilia_state
    ):
        commands.execute("media.seek", 0)
        _trigger_seek(tluis, "+99m")
        # Only 2 measures; last starts at t=4.
        assert tilia_state.player.current_time == 4

    def test_absolute_measure_out_of_range_clamps(
        self, tluis, beats_in_two_measures, tilia_state
    ):
        _trigger_seek(tluis, "99m")
        # Clamped to last measure (2) — its first beat is at t=4.
        assert tilia_state.player.current_time == 4

    def test_absolute_beat_out_of_range_clamps(
        self, tluis, beats_in_two_measures, tilia_state
    ):
        _trigger_seek(tluis, "999b")
        assert tilia_state.player.current_time == 6


class TestSeekErrors:
    def test_no_beat_timeline_for_measure_seek(self, tluis, tilia_state, tilia_errors):
        _trigger_seek(tluis, "1")
        tilia_errors.assert_error()
        tilia_errors.assert_in_error_title("Seek")

    def test_no_beat_timeline_for_beat_seek(self, tluis, tilia_state, tilia_errors):
        _trigger_seek(tluis, "+1b")
        tilia_errors.assert_error()
        tilia_errors.assert_in_error_title("Seek")

    def test_invalid_input_shows_error(self, tluis, tilia_state, tilia_errors):
        _trigger_seek(tluis, "not a seek")
        tilia_errors.assert_error()
        tilia_errors.assert_in_error_title("Seek")

    def test_finds_beat_timeline_with_any_name(
        self, tluis, beats_in_two_measures, tilia_state
    ):
        # Regression: the seek code used to require a timeline literally
        # named "Measures". Make sure renaming the timeline doesn't break
        # the lookup.
        beats_in_two_measures.timeline.set_data("name", "Battute")
        _trigger_seek(tluis, "2")
        assert tilia_state.player.current_time == 4
