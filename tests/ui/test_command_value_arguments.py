"""Commands that ask the user for a value also accept it as an argument.

When the value is passed, the dialog must not be consulted. Each test
answers the dialog with "cancel", so a command that still asked would
change nothing and the test would fail.
"""

import pytest
from PySide6.QtGui import QColor

from tests.mock import Serve
from tilia.requests import Get
from tilia.ui import commands


class TestSetAmountInMeasure:
    @pytest.fixture(autouse=True)
    def _two_measures(self, beat_tlui):
        beat_tlui.timeline.beat_pattern = [4]
        for time in range(8):
            commands.execute("timeline.beat.add", time=time)
        assert beat_tlui.timeline.beats_in_measure == [4, 4]
        beat_tlui.select_element(beat_tlui[0])

    def test_takes_the_amount_as_an_argument(self, beat_tlui):
        with Serve(Get.FROM_USER_INT, (False, 0)):
            commands.execute("timeline.beat.set_amount_in_measure", amount=3)

        assert beat_tlui.timeline.beats_in_measure[0] == 3

    def test_refuses_an_amount_the_dialog_would_not_accept(self, beat_tlui):
        with Serve(Get.FROM_USER_INT, (True, 3)):
            commands.execute("timeline.beat.set_amount_in_measure", amount=0)

        assert beat_tlui.timeline.beats_in_measure == [4, 4]


class TestAddPreStartAndPostEnd:
    @pytest.fixture(autouse=True)
    def _unit(self, hierarchy_tlui, tilia_state):
        assert tilia_state.duration == 100
        commands.execute("timeline.hierarchy.add", start=10, end=50, level=1)
        hierarchy_tlui.select_element(hierarchy_tlui[0])

    def test_pre_start_takes_the_length_as_an_argument(self, hierarchy_tlui):
        with Serve(Get.FROM_USER_FLOAT, (False, 0)):
            commands.execute("timeline.hierarchy.add_pre_start", length=5)

        assert hierarchy_tlui[0].get_data("pre_start") == 10 - 5

    def test_post_end_takes_the_length_as_an_argument(self, hierarchy_tlui):
        with Serve(Get.FROM_USER_FLOAT, (False, 0)):
            commands.execute("timeline.hierarchy.add_post_end", length=5)

        assert hierarchy_tlui[0].get_data("post_end") == 50 + 5

    @pytest.mark.parametrize(
        "command,length",
        [
            ("timeline.hierarchy.add_pre_start", 0),
            ("timeline.hierarchy.add_pre_start", 11),
            ("timeline.hierarchy.add_post_end", 0),
            ("timeline.hierarchy.add_post_end", 51),
        ],
        ids=[
            "pre-start-too-short",
            "pre-start-before-0",
            "post-end-too-short",
            "post-end-past-end",
        ],
    )
    def test_refuses_a_length_the_dialog_would_not_accept(
        self, hierarchy_tlui, command, length
    ):
        # The dialog caps a pre-start at the unit's start and a post-end at
        # the media's end, and neither may be shorter than MIN_FRAME_LENGTH.
        with Serve(Get.FROM_USER_FLOAT, (True, 5)):
            commands.execute(command, length=length)

        assert hierarchy_tlui[0].get_data("pre_start") == 10
        assert hierarchy_tlui[0].get_data("post_end") == 50


class TestSetColor:
    def test_takes_the_color_as_an_argument(self, marker_tlui):
        commands.execute("timeline.marker.add")
        marker_tlui.select_element(marker_tlui[0])

        with Serve(Get.FROM_USER_COLOR, (False, QColor())):
            commands.execute("timeline.component.set_color", color=QColor("#ff0000"))

        assert marker_tlui[0].get_data("color") == "#ff0000"

    def test_refuses_an_invalid_color(self, marker_tlui):
        commands.execute("timeline.marker.add")
        marker_tlui.select_element(marker_tlui[0])
        color_before = marker_tlui[0].get_data("color")

        with Serve(Get.FROM_USER_COLOR, (True, QColor("#ff0000"))):
            commands.execute("timeline.component.set_color", color=QColor())

        assert marker_tlui[0].get_data("color") == color_before
