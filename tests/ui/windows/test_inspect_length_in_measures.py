"""Tests for the 'Length (measures)' inspector row on hierarchy/range.

The row appears whenever a beat timeline is present and the component
spans at least one full measure-fraction; otherwise it's hidden (the
inspector framework supports `HIDE_FIELD` for that). The value is
formatted as 'N m.' or 'N m. B b.' by `format_length_in_measures`.
"""

import pytest

from tilia.requests import Post, post
from tilia.ui import commands
from tilia.ui.windows.kinds import WindowKind


@pytest.fixture(autouse=True)
def close_inspector():
    yield
    post(Post.WINDOW_CLOSE, WindowKind.INSPECT)


def _open_inspector_for(tlui, element, qtui):
    tlui.select_element(element)
    commands.execute("timeline.element.inspect")
    return qtui._windows[WindowKind.INSPECT]


def _make_grid_of_three_measures(beat_tlui):
    """Beat layout: t=0..8 with pattern [3] gives measures of length 3.

    Measure 1: t=0, t=1, t=2
    Measure 2: t=3, t=4, t=5
    Measure 3: t=6, t=7, t=8
    """
    beat_tlui.timeline.beat_pattern = [3]
    for t in (0, 1, 2, 3, 4, 5, 6, 7, 8):
        commands.execute("media.seek", t)
        commands.execute("timeline.beat.add")
    beat_tlui.timeline.recalculate_measures()


class TestLengthInMeasuresInspector:
    def test_hierarchy_whole_measures(self, qtui, hierarchy_tlui, beat_tlui):
        _make_grid_of_three_measures(beat_tlui)
        hierarchy_tlui.create_hierarchy(0, 3, 1)  # measure 1 only
        element = hierarchy_tlui[0]

        inspector = _open_inspector_for(hierarchy_tlui, element, qtui)
        value_label = inspector.field_name_to_widgets["Length (measures)"][1]

        assert value_label.text() == "1 m."

    def test_hierarchy_measures_and_beats(self, qtui, hierarchy_tlui, beat_tlui):
        # Spans measure 1 (3 beats) + first beat of measure 2.
        _make_grid_of_three_measures(beat_tlui)
        hierarchy_tlui.create_hierarchy(0, 4, 1)
        element = hierarchy_tlui[0]

        inspector = _open_inspector_for(hierarchy_tlui, element, qtui)
        value_label = inspector.field_name_to_widgets["Length (measures)"][1]

        assert value_label.text() == "1 m. 1 b."

    def test_hierarchy_row_hidden_without_beat_timeline(self, qtui, hierarchy_tlui):
        hierarchy_tlui.create_hierarchy(0, 3, 1)
        element = hierarchy_tlui[0]

        inspector = _open_inspector_for(hierarchy_tlui, element, qtui)
        value_label = inspector.field_name_to_widgets["Length (measures)"][1]

        # HIDE_FIELD path: the row's value widget is invisible.
        assert not value_label.isVisible()

    def test_range_length_in_measures(self, qtui, range_tlui, beat_tlui):
        _make_grid_of_three_measures(beat_tlui)
        commands.execute("timeline.range.add_range", start=0, end=6)
        element = range_tlui[0]

        inspector = _open_inspector_for(range_tlui, element, qtui)
        value_label = inspector.field_name_to_widgets["Length (measures)"][1]

        assert value_label.text() == "2 m."
