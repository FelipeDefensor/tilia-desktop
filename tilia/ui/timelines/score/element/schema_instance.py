from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsSimpleTextItem

from tilia.ui.coords import time_x_converter
from tilia.ui.timelines.base.element import TimelineUIElement
from tilia.ui.windows.svg_viewer import SvgViewer

SPAN_ALPHA = 170
LABEL_PADDING = 4
LABEL_FONT_SIZE = 8


class SchemaSpanBody(QGraphicsRectItem):
    def __init__(self, color: QColor):
        super().__init__()
        fill = QColor(color)
        fill.setAlpha(SPAN_ALPHA)
        self.setBrush(fill)
        self.set_selected(False)

    def set_selected(self, selected: bool) -> None:
        pen = QPen(QColor("black"))
        pen.setStyle(Qt.PenStyle.SolidLine if selected else Qt.PenStyle.NoPen)
        self.setPen(pen)


class SchemaInstanceUI(TimelineUIElement):
    """A schema instance as bars in the score timeline's schema lane, one per
    pass through its measures, like ranges in a range timeline.

    Its degrees are drawn on the score viewer. The lane's rows and the bars'
    times come from the timeline UI (see `ScoreTimelineUI.update_schema_lane`).
    """

    UPDATE_TRIGGERS = ["schema", "degrees"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.spans: list[tuple[float, float]] = []
        self.row = 0
        self.bodies: list[SchemaSpanBody] = []
        self.labels: list[QGraphicsSimpleTextItem] = []
        self.svg_view.update_schema_instance(self.id)

    @property
    def svg_view(self) -> SvgViewer:
        return self.timeline_ui.get_or_create_svg_view()

    @property
    def color(self) -> QColor:
        return QColor(self.get_data("schema").get("color") or "gray")

    @property
    def seek_time(self) -> float | None:
        return self.spans[0][0] if self.spans else None

    def set_layout(self, spans: list[tuple[float, float]], row: int) -> None:
        self.spans = spans
        self.row = row
        if len(self.bodies) != len(spans):
            self._remove_items()
            for _ in spans:
                body = SchemaSpanBody(self.color)
                label = QGraphicsSimpleTextItem(self.get_data("schema")["name"])
                label.setFont(QFont("Arial", LABEL_FONT_SIZE))
                self.scene.addItem(body)
                self.scene.addItem(label)
                self.bodies.append(body)
                self.labels.append(label)
        self.update_position()

    def _remove_items(self) -> None:
        for item in [*self.bodies, *self.labels]:
            if item.scene() is self.scene:
                self.scene.removeItem(item)
        self.bodies, self.labels = [], []

    def update_position(self) -> None:
        if not self.bodies:
            return
        y = self.timeline_ui.schema_row_y(self.row)
        height = self.timeline_ui.SCHEMA_ROW_HEIGHT
        name = self.get_data("schema")["name"]
        for (start, end), body, label in zip(
            self.spans, self.bodies, self.labels, strict=True
        ):
            x0 = time_x_converter.get_x_by_time(start)
            x1 = time_x_converter.get_x_by_time(end)
            body.setRect(QRectF(x0, y, max(1.0, x1 - x0), height))
            # Cut the name to the bar, as range labels are.
            width = x1 - x0 - 2 * LABEL_PADDING
            label.setVisible(width > 0)
            label.setText(
                QFontMetricsF(label.font()).elidedText(
                    name, Qt.TextElideMode.ElideRight, max(0.0, width)
                )
            )
            label.setPos(
                x0 + LABEL_PADDING, y + (height - label.boundingRect().height()) / 2
            )

    def update_schema(self):
        self.svg_view.update_schema_instance(self.id)
        self.timeline_ui.update_schema_lane()

    def update_degrees(self):
        self.svg_view.update_schema_instance(self.id)
        self.timeline_ui.update_schema_lane()

    def delete(self):
        self._remove_items()
        # Don't create a viewer just to remove the instance from it.
        if (viewer := self.timeline_ui.svg_view) is not None:
            viewer.remove_schema_instance(self.id)
        return super().delete()

    def child_items(self) -> list[QGraphicsItem]:
        return [*self.bodies, *self.labels]

    def left_click_triggers(self) -> list[QGraphicsItem]:
        return self.child_items()

    def on_left_click(self, _: QGraphicsItem) -> None:
        # Continue the instance in the score viewer, and show it there.
        viewer = self.svg_view
        viewer.set_active_schema_instance(self.id)
        if self.spans:
            viewer.scroll_to_time(self.spans[0][0], True)

    def on_select(self) -> None:
        for body in self.bodies:
            body.set_selected(True)

    def on_deselect(self) -> None:
        for body in self.bodies:
            body.set_selected(False)
