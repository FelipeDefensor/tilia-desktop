"""Tests for decorative scene items (hover line, row highlight, etc.)
that should be transparent to clicks.

The `ignore_right_click` attribute already filters items out of the
right-click path. The hover guideline introduced in feat/hover-guideline
exposed the symmetric gap on the LEFT-click path: when the hover line
sat on top of a beat or hierarchy element, single-clicking that element
landed on the hover line instead, so click-to-seek and click-to-select
both silently dropped.
"""

from unittest.mock import patch

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from tilia.requests import Post, listen, stop_listening
from tilia.ui import commands
from tilia.ui.coords import time_x_converter


def _click_view_at(view, x: float, y: float, button: Qt.MouseButton) -> None:
    """Build a real QMouseEvent and dispatch through the view's own
    mousePressEvent, so we exercise the ignore_* filter rather than
    going around it via the test-only click helpers."""
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(x, y),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )
    view.mousePressEvent(event)


class _ClickCollector:
    """Hashable listener (lists aren't, but objects are by default)."""

    def __init__(self):
        self.calls = []


def _collect_clicks(post_):
    collector = _ClickCollector()

    def on_click(view, x, y, item, modifier, double):
        collector.calls.append({"view": view, "x": x, "y": y, "item": item})

    listen(collector, post_, on_click)
    return collector, lambda: stop_listening(collector, post_)


class TestHoverLineDoesNotInterceptClicks:
    def test_left_click_passes_through_to_beat(self, beat_tlui, tilia_state):
        # Put a beat at t=2 so we have a concrete element to click.
        commands.execute("media.seek", 2)
        commands.execute("timeline.beat.add")
        beat = beat_tlui[0]

        view = beat_tlui.view
        x = int(time_x_converter.get_x_by_time(2))
        y = int(beat_tlui.get_data("height") / 2)

        # Pretend the user just hovered over the beat — the hover
        # guideline is visible at exactly x.
        beat_tlui.scene.set_hover_line_pos(x)

        collector, cleanup = _collect_clicks(Post.TIMELINE_VIEW_LEFT_CLICK)
        try:
            _click_view_at(view, x, y, Qt.MouseButton.LeftButton)
        finally:
            cleanup()

        assert len(collector.calls) == 1
        clicked_item = collector.calls[0]["item"]
        # The beat owns several scene items; the only thing that matters
        # for the seek/select side-effects is that the clicked item is
        # owned by an element. If we accidentally land on the hover
        # line, `get_item_owner` will be empty.
        assert clicked_item in beat.child_items(), (
            f"Click landed on {clicked_item!r}, "
            "expected an item owned by the beat element."
        )

    def test_right_click_passes_through_to_beat(self, beat_tlui, tilia_state):
        commands.execute("media.seek", 2)
        commands.execute("timeline.beat.add")
        beat = beat_tlui[0]

        view = beat_tlui.view
        x = int(time_x_converter.get_x_by_time(2))
        y = int(beat_tlui.get_data("height") / 2)
        beat_tlui.scene.set_hover_line_pos(x)

        collector, cleanup = _collect_clicks(Post.TIMELINE_VIEW_RIGHT_CLICK)
        # Right-click eventually triggers `QMenu.exec()` which blocks the
        # test thread. Short-circuit it; we only care that the click
        # landed on the beat in the first place.
        try:
            with patch.object(
                __import__(
                    "tilia.ui.timelines.beat.context_menu",
                    fromlist=["BeatContextMenu"],
                ).BeatContextMenu,
                "exec",
                return_value=None,
            ):
                _click_view_at(view, x, y, Qt.MouseButton.RightButton)
        finally:
            cleanup()

        assert len(collector.calls) == 1
        clicked_item = collector.calls[0]["item"]
        assert clicked_item in beat.child_items(), (
            f"Right-click landed on {clicked_item!r}, "
            "expected an item owned by the beat element."
        )

    def test_left_click_passes_through_to_higher_level_hierarchy(
        self, hierarchy_tlui, tilia_state
    ):
        # Hierarchy bodies have z = -level, hover_line is at z = -1.
        # A level-2 hierarchy sits BELOW the hover line in stacking order
        # — when the user hovers over the body and clicks, itemAt returns
        # the hover line and the click never reaches the hierarchy.
        hierarchy_tlui.create_hierarchy(2, 8, 2)
        hierarchy = hierarchy_tlui[0]

        # Click squarely inside the body's bounding rect so there's no
        # ambiguity about whether the click hit it.
        body_rect = hierarchy.body.sceneBoundingRect()
        x = int(body_rect.center().x())
        y = int(body_rect.center().y())
        view = hierarchy_tlui.view
        hierarchy_tlui.scene.set_hover_line_pos(x)

        collector, cleanup = _collect_clicks(Post.TIMELINE_VIEW_LEFT_CLICK)
        try:
            _click_view_at(view, x, y, Qt.MouseButton.LeftButton)
        finally:
            cleanup()

        assert len(collector.calls) == 1
        clicked_item = collector.calls[0]["item"]
        assert clicked_item in hierarchy.child_items(), (
            f"Click landed on {clicked_item!r}, "
            "expected an item owned by the hierarchy element."
        )

    def test_left_click_on_empty_space_with_hover_line_returns_no_item(self, beat_tlui):
        # Hover line shouldn't *invent* a click target either — clicking
        # empty timeline space should still produce a None item so the
        # left-click handler triggers the usual deselect-all path.
        view = beat_tlui.view
        # Pick coordinates within the playback area but past any beats.
        x = int(time_x_converter.get_x_by_time(10))
        y = int(beat_tlui.get_data("height") / 2)
        beat_tlui.scene.set_hover_line_pos(x)

        collector, cleanup = _collect_clicks(Post.TIMELINE_VIEW_LEFT_CLICK)
        try:
            _click_view_at(view, x, y, Qt.MouseButton.LeftButton)
        finally:
            cleanup()

        assert len(collector.calls) == 1
        assert collector.calls[0]["item"] is None
