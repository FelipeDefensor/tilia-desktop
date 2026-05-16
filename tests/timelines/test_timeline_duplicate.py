import pytest

from tilia.timelines.base.timeline import TimelineFlag
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.marker.timeline import MarkerTimeline


class TestDuplicateTimeline:
    def test_returns_new_timeline_of_same_kind(self, marker_tl, tls):
        dup = tls.duplicate_timeline(marker_tl)

        assert dup is not None
        assert type(dup) is type(marker_tl)
        assert dup.id != marker_tl.id

    def test_appends_copy_suffix_to_name(self, marker_tl, tls):
        marker_tl.set_data("name", "Phrases")

        dup = tls.duplicate_timeline(marker_tl)

        assert dup.get_data("name") == "Phrases (copy)"

    def test_inserts_immediately_below_source(self, tls):
        tl1 = tls.create_timeline(MarkerTimeline)
        tl2 = tls.create_timeline(MarkerTimeline)
        tl3 = tls.create_timeline(MarkerTimeline)

        dup = tls.duplicate_timeline(tl1)

        assert tl1.get_data("ordinal") == 1
        assert dup.get_data("ordinal") == 2
        assert tl2.get_data("ordinal") == 3
        assert tl3.get_data("ordinal") == 4

    def test_inserts_at_end_when_source_is_last(self, tls):
        tl1 = tls.create_timeline(MarkerTimeline)
        tl2 = tls.create_timeline(MarkerTimeline)

        dup = tls.duplicate_timeline(tl2)

        assert tl1.get_data("ordinal") == 1
        assert tl2.get_data("ordinal") == 2
        assert dup.get_data("ordinal") == 3

    def test_components_are_copied_with_fresh_ids(self, marker_tl, tls):
        marker_tl.create_marker(10)
        marker_tl.create_marker(20)
        marker_tl.create_marker(30)

        dup = tls.duplicate_timeline(marker_tl)

        assert len(dup) == len(marker_tl)
        source_times = sorted(c.get_data("time") for c in marker_tl)
        dup_times = sorted(c.get_data("time") for c in dup)
        assert source_times == dup_times

        source_ids = {c.id for c in marker_tl}
        dup_ids = {c.id for c in dup}
        assert source_ids.isdisjoint(dup_ids)

    def test_editing_duplicate_does_not_affect_source(self, marker_tl, tls):
        marker_tl.create_marker(10)
        original_count = len(marker_tl)

        dup = tls.duplicate_timeline(marker_tl)
        dup.create_component(ComponentKind.MARKER, time=50)

        assert len(marker_tl) == original_count
        assert len(dup) == original_count + 1

    def test_slider_is_not_duplicable(self, slider_tl, tls):
        before = len(tls)

        result = tls.duplicate_timeline(slider_tl)

        assert result is None
        assert len(tls) == before

    def test_audiowave_is_not_duplicable(self, audiowave_tl, tls):
        before = len(tls)

        result = tls.duplicate_timeline(audiowave_tl)

        assert result is None
        assert len(tls) == before

    def test_score_is_not_duplicable(self, score_tl, tls):
        before = len(tls)

        result = tls.duplicate_timeline(score_tl)

        assert result is None
        assert len(tls) == before

    def test_duplicate_preserves_height_and_visibility(self, marker_tl, tls):
        marker_tl.set_data("height", 123)
        marker_tl.set_data("is_visible", False)

        dup = tls.duplicate_timeline(marker_tl)

        assert dup.get_data("height") == 123
        assert dup.get_data("is_visible") is False

    @pytest.mark.parametrize(
        "kind_name",
        ["marker_tl", "hierarchy_tl", "beat_tl", "harmony_tl"],
    )
    def test_duplicate_each_kind(self, kind_name, tls, request):
        source = request.getfixturevalue(kind_name)
        before = len(tls)

        dup = tls.duplicate_timeline(source)

        assert dup is not None
        assert type(dup) is type(source)
        assert TimelineFlag.NOT_DUPLICABLE not in source.FLAGS
        assert len(tls) == before + 1
