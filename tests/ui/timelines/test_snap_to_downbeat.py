"""Tests for the snap-to-downbeat context-menu command.

These exercise the full command path: a beat timeline supplies the
metric grid, then a selected hierarchy/range/marker/pdf component is
snapped via `commands.execute("timeline.component.snap_to_downbeat")`.
The collaborator timelines and elements are wired up through fixtures,
mirroring how a user would set them up in the GUI.

Downbeat == first beat of a measure (i.e. the measure start). The
"any beat" variant was removed — there's only one snap target now.
"""

import pytest

from tilia.requests import Post, listen, stop_listening
from tilia.ui import commands


def _build_two_measure_grid(beat_tlui):
    """Beat layout: 0, 1, 2 (measure 1) and 4, 5, 6 (measure 2).

    Pattern is [3] so every third beat starts a measure. The gap between
    beats 2 and 4 creates a meaningful asymmetric distance for snap
    tests (a value just past 2 should snap to 2, not 4).
    """
    beat_tlui.timeline.beat_pattern = [3]
    for time in (0, 1, 2, 4, 5, 6):
        commands.execute("media.seek", time)
        commands.execute("timeline.beat.add")
    beat_tlui.timeline.recalculate_measures()
    return beat_tlui


@pytest.fixture
def measure_grid(beat_tlui):
    return _build_two_measure_grid(beat_tlui)


class TestSnapToDownbeatHierarchy:
    def test_moves_start_to_nearest_downbeat_backward(
        self, hierarchy_tlui, measure_grid
    ):
        # Component starts just after measure 1's downbeat; nearest
        # downbeat (at t=0) is backward.
        hierarchy_tlui.create_hierarchy(0.3, 3.5, 1)
        hierarchy_tlui.select_element(hierarchy_tlui[0])

        commands.execute("timeline.component.snap_to_downbeat")

        assert hierarchy_tlui[0].get_data("start") == 0

    def test_moves_start_to_nearest_downbeat_forward(
        self, hierarchy_tlui, measure_grid
    ):
        # Component starts at 3.5 — closer to measure 2's downbeat (t=4)
        # than to measure 1's downbeat (t=0).
        hierarchy_tlui.create_hierarchy(3.5, 6.5, 1)
        hierarchy_tlui.select_element(hierarchy_tlui[0])

        commands.execute("timeline.component.snap_to_downbeat")

        assert hierarchy_tlui[0].get_data("start") == 4

    def test_skips_non_downbeat_beats(self, hierarchy_tlui, measure_grid):
        # Component starts at 1.3 — closest *any* beat is at 1, but the
        # closest *downbeat* is at 0 (measure 1's downbeat). Snap must
        # pick the downbeat, not the closer non-downbeat beat.
        hierarchy_tlui.create_hierarchy(1.3, 3, 1)
        hierarchy_tlui.select_element(hierarchy_tlui[0])

        commands.execute("timeline.component.snap_to_downbeat")

        assert hierarchy_tlui[0].get_data("start") == 0

    def test_pulls_adjacent_end_with_it(self, hierarchy_tlui, measure_grid):
        # Two adjacent hierarchies share t=3.5 (A.end == B.start).
        # 3.5 is closer to 4 than to 0, so snap forward — A's end should
        # move to 4 too.
        hierarchy_tlui.create_hierarchy(0, 3.5, 1)
        hierarchy_tlui.create_hierarchy(3.5, 6.5, 1)
        hierarchy_tlui.select_element(hierarchy_tlui[1])

        commands.execute("timeline.component.snap_to_downbeat")

        assert hierarchy_tlui[0].get_data("end") == 4
        assert hierarchy_tlui[1].get_data("start") == 4

    def test_pulls_parent_start_with_it(self, hierarchy_tlui, measure_grid):
        # Parent at level 2 starts at the same time as the child at
        # level 1; snapping the child's start should drag the parent
        # along.
        hierarchy_tlui.create_hierarchy(0.3, 3, 2)  # parent
        hierarchy_tlui.create_hierarchy(0.3, 3, 1)  # child
        hierarchy_tlui.select_element(hierarchy_tlui[1])

        commands.execute("timeline.component.snap_to_downbeat")

        assert hierarchy_tlui[0].get_data("start") == 0
        assert hierarchy_tlui[1].get_data("start") == 0

    def test_noop_when_already_on_downbeat(self, hierarchy_tlui, measure_grid):
        hierarchy_tlui.create_hierarchy(4, 6, 1)
        hierarchy_tlui.select_element(hierarchy_tlui[0])

        commands.execute("timeline.component.snap_to_downbeat")

        assert hierarchy_tlui[0].get_data("start") == 4

    def test_error_when_no_beat_timeline(
        self, hierarchy_tlui, tilia_state, tilia_errors
    ):
        # No beat timeline created in this test.
        hierarchy_tlui.create_hierarchy(0.3, 3, 1)
        hierarchy_tlui.select_element(hierarchy_tlui[0])

        commands.execute("timeline.component.snap_to_downbeat")

        tilia_errors.assert_error()
        assert hierarchy_tlui[0].get_data("start") == 0.3

    def test_posts_set_data_done_so_ui_redraws(self, hierarchy_tlui, measure_grid):
        # Regression test for the snap-doesn't-move bug: the snap loop
        # used to call `component.set_data` directly, which updates the
        # backend but skips the post that triggers the UI to redraw the
        # moved scene items. Going through `timeline.set_component_data`
        # fires the post — assert we see it for both the snapped start
        # and the pulled-along end.
        hierarchy_tlui.create_hierarchy(0, 3.5, 1)
        hierarchy_tlui.create_hierarchy(3.5, 6.5, 1)
        hierarchy_tlui.select_element(hierarchy_tlui[1])

        posts: list[tuple] = []

        def _record(timeline_id, component_id, attr, value):
            posts.append((component_id, attr, value))

        listen(_record, Post.TIMELINE_COMPONENT_SET_DATA_DONE, _record)
        try:
            commands.execute("timeline.component.snap_to_downbeat")
        finally:
            stop_listening(_record, Post.TIMELINE_COMPONENT_SET_DATA_DONE)

        changed_attrs = {(attr, value) for _, attr, value in posts}
        assert ("start", 4) in changed_attrs
        assert ("end", 4) in changed_attrs


class TestSnapToDownbeatAfterDeserialize:
    def test_snap_works_when_per_beat_flag_was_not_persisted(
        self, hierarchy_tlui, measure_grid
    ):
        # Beat.SERIALIZABLE = ["time"] — `is_first_in_measure` is not in
        # the .tla payload. After load, every beat comes back with the
        # default `is_first_in_measure = False`. `recalculate_measures()`
        # updates the timeline-level `beats_that_start_measures` but not
        # the per-beat flag, so snap must work off the timeline data.
        for beat in measure_grid.timeline.components:
            beat.is_first_in_measure = False

        hierarchy_tlui.create_hierarchy(0.3, 3.5, 1)
        hierarchy_tlui.select_element(hierarchy_tlui[0])

        commands.execute("timeline.component.snap_to_downbeat")

        assert hierarchy_tlui[0].get_data("start") == 0


class TestSnapMarker:
    def test_snap_to_downbeat_moves_marker(self, marker_tlui, measure_grid):
        marker_tlui.create_marker(0.3)
        marker_tlui.select_element(marker_tlui[0])

        commands.execute("timeline.component.snap_to_downbeat")

        assert marker_tlui[0].get_data("time") == 0


class TestSnapRange:
    def test_snap_to_downbeat_moves_range_start(self, range_tlui, measure_grid):
        commands.execute("timeline.range.add_range", start=0.3, end=3)
        range_tlui.select_element(range_tlui[0])

        commands.execute("timeline.component.snap_to_downbeat")

        assert range_tlui[0].get_data("start") == 0
