"""Tests for the hover guideline (vertical line under the cursor).

The line is per-timeline-scene; `Post.TIMELINE_VIEW_HOVER` is fanned
out by `TimelineUIs._on_timeline_view_hover` to every scene's
`set_hover_line_pos`. A View-menu toggle persisted in the `general/
show_hover_guideline` setting controls whether the line is drawn at all.
"""

import pytest

from tilia.requests import Post, post
from tilia.settings import settings


@pytest.fixture(autouse=True)
def restore_hover_setting():
    yield
    settings.set("general", "show_hover_guideline", True)


def _hover_x(x):
    post(Post.TIMELINE_VIEW_HOVER, x)


def _hover_clear():
    post(Post.TIMELINE_VIEW_HOVER, None)


class TestHoverGuideline:
    def test_hover_x_makes_line_visible_on_every_timeline(
        self, hierarchy_tlui, beat_tlui
    ):
        # Two different timeline UIs — both should reflect the cursor.
        _hover_x(120)

        for tlui in (hierarchy_tlui, beat_tlui):
            assert (
                tlui.scene.hover_line.isVisible()
            ), f"hover_line on {type(tlui).__name__} not visible after hover"

    def test_hover_none_hides_line_on_every_timeline(self, hierarchy_tlui, beat_tlui):
        _hover_x(120)
        _hover_clear()

        for tlui in (hierarchy_tlui, beat_tlui):
            assert not tlui.scene.hover_line.isVisible()

    def test_setting_disabled_keeps_line_hidden(self, hierarchy_tlui):
        settings.set("general", "show_hover_guideline", False)

        _hover_x(120)

        assert not hierarchy_tlui.scene.hover_line.isVisible()

    def test_re_enabling_setting_brings_line_back(self, hierarchy_tlui):
        settings.set("general", "show_hover_guideline", False)
        _hover_x(120)
        assert not hierarchy_tlui.scene.hover_line.isVisible()

        settings.set("general", "show_hover_guideline", True)
        _hover_x(120)

        assert hierarchy_tlui.scene.hover_line.isVisible()


class TestHoverGuidelineLine:
    def test_line_x_follows_cursor(self, beat_tlui):
        _hover_x(150)
        line = beat_tlui.scene.hover_line.line()
        assert line.x1() == 150
        assert line.x2() == 150

    def test_line_spans_scene_height(self, beat_tlui):
        # The hover line should be a full-height vertical, not a stub.
        _hover_x(150)
        line = beat_tlui.scene.hover_line.line()
        assert line.y1() == 0
        assert line.y2() == beat_tlui.scene.height()
