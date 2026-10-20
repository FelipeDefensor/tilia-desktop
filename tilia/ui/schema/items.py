"""What schema instances look like on the score.

The degree circles go in bands above and below the system, not on the
staves, so they never cover the notes: upper-voice degrees above, inner and
bass degrees below, each circle at its note's x. A thin ring around each
marked notehead shows which note it stands for. Instances whose degrees
would collide take separate rows in a band, like ranges in a range timeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsSceneMouseEvent,
    QGraphicsSimpleTextItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from tilia.timelines.score.schema import VOICES, degree_label
from tilia.ui.schema.diagram import PLACED_RING_DARKER, paint_degree

# All sizes are relative to the score's typical notehead height, so they keep
# their proportion to the score whatever its zoom.
DEGREE_RADIUS_FACTOR = 0.8
LABEL_FONT_FACTOR = 1.6
LINE_WIDTH_FACTOR = 0.6
# Between the system and the first row, between rows, and between instances
# sharing a row.
BAND_GAP_FACTOR = 1.5
ROW_GAP_FACTOR = 0.6
INSTANCE_GAP_FACTOR = 1.0
HALO_MARGIN_FACTOR = 0.25
HALO_STEP_FACTOR = 0.3
HALO_WIDTH_FACTOR = 0.18
MIN_RADIUS = 4.0
SELECTED_COLOR = QColor("red")
Z_VALUE = 3


class SvgSchemaDegree(QGraphicsItem):
    """A placed degree's circle."""

    def __init__(
        self,
        instance_id: int,
        placed: dict,
        center: QPointF,
        radius: float,
        color: QColor,
        on_press: Callable[[SvgSchemaDegree, Qt.KeyboardModifier], None],
        on_double_click: Callable[[SvgSchemaDegree], None],
    ):
        super().__init__()
        self.instance_id = instance_id
        self.placed = placed
        self.color = color
        self.ring_color = color.darker(PLACED_RING_DARKER)
        self.on_press = on_press
        self.on_double_click = on_double_click
        self.radius = radius
        self.setPos(center)
        self.setZValue(Z_VALUE)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setToolTip(
            f"Stage {placed['stage'] + 1}, {placed['voice']}: "
            f"{self.label} (Shift+click to remove)"
        )

    @property
    def notehead(self) -> str:
        return self.placed["notehead"]

    @property
    def label(self) -> str:
        return degree_label(self.placed["value"], self.placed.get("accidental", "="))

    def boundingRect(self) -> QRectF:
        r = self.radius + 2
        return QRectF(-r, -r, 2 * r, 2 * r)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        paint_degree(
            painter,
            QPointF(0, 0),
            self.radius,
            self.placed["voice"],
            self.label,
            ring_color=SELECTED_COLOR if self.isSelected() else self.ring_color,
        )

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        self.on_press(self, event.modifiers())
        if Qt.KeyboardModifier.ShiftModifier in event.modifiers():
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        self.on_double_click(self)
        super().mouseDoubleClickEvent(event)


@dataclass
class SvgSchemaInstance:
    """All the scene items of one schema instance."""

    instance_id: int
    schema: dict
    degrees: list[SvgSchemaDegree] = field(default_factory=list)
    lines: list[QGraphicsPathItem] = field(default_factory=list)
    halos: list[QGraphicsEllipseItem] = field(default_factory=list)
    label: QGraphicsSimpleTextItem | None = None

    @property
    def color(self) -> QColor:
        return QColor(self.schema.get("color") or "black")

    def items(self) -> list[QGraphicsItem]:
        return [
            *self.halos,
            *self.lines,
            *self.degrees,
            *([self.label] if self.label else []),
        ]


def _assign_rows(extents: list[tuple[int, float, float]]) -> dict[int, int]:
    """Rows for (id, left, right) extents, so that none overlap in a row:
    each goes in the first row it fits in, from left to right."""
    rows: list[float] = []  # each row's rightmost edge
    result = {}
    for id, left, right in sorted(extents, key=lambda e: (e[1], e[0])):
        for row, edge in enumerate(rows):
            if edge < left:
                rows[row] = right
                result[id] = row
                break
        else:
            rows.append(right)
            result[id] = len(rows) - 1
    return result


def layout_schema_instances(
    instances: list[tuple[int, dict, list[dict]]],
    noteheads: dict[str, QRectF],
    system: QRectF,
    unit: float,
    on_press: Callable[[SvgSchemaDegree, Qt.KeyboardModifier], None],
    on_double_click: Callable[[SvgSchemaDegree], None],
) -> dict[int, SvgSchemaInstance]:
    """Builds the scene items for (id, schema, placed degrees) instances.

    `system` is the rect of the staves and everything on them, so the bands
    go outside it. Degrees on noteheads not in `noteheads` are skipped.
    """
    radius = max(MIN_RADIUS, unit * DEGREE_RADIUS_FACTOR)
    row_gap = unit * ROW_GAP_FACTOR
    font = QFont()
    font.setPixelSize(max(6, round(unit * LABEL_FONT_FACTOR)))
    font.setBold(True)
    metrics = QFontMetricsF(font)
    label_height = metrics.height()
    circle_row = 2 * radius + row_gap

    placed_by_id = {
        id: [d for d in degrees if d["notehead"] in noteheads]
        for id, _, degrees in instances
    }
    has_inner = any(
        d["voice"] == "inner" for degrees in placed_by_id.values() for d in degrees
    )

    def x_of(d: dict) -> float:
        return noteheads[d["notehead"]].center().x() + d["index"] * (2 * radius + 2)

    # A row in a band holds an instance from its first circle to its last,
    # or to the end of its name, in the band that shows it, if that is longer.
    # The name goes over the upper voice, or under the bass if it has none.
    upper_extents, lower_extents = [], []
    for id, schema, _ in instances:
        degrees = placed_by_id[id]
        if not degrees:
            continue
        gap = unit * INSTANCE_GAP_FACTOR
        has_upper = any(d["voice"] == "upper" for d in degrees)
        for band, voices, labelled in (
            (upper_extents, ("upper",), True),
            (lower_extents, ("inner", "lower"), not has_upper),
        ):
            xs = [x_of(d) for d in degrees if d["voice"] in voices]
            if not xs:
                continue
            left = min(xs) - radius
            right = max(xs) + radius
            if labelled:
                right = max(right, left + metrics.horizontalAdvance(schema["name"]))
            band.append((id, left - gap / 2, right + gap / 2))
    upper_rows = _assign_rows(upper_extents)
    lower_rows = _assign_rows(lower_extents)

    upper_slot = label_height + circle_row
    lower_slot = circle_row * (2 if has_inner else 1) + label_height
    halos_on: dict[str, int] = {}

    result = {}
    for id, schema, _ in sorted(instances, key=lambda i: i[0]):
        drawn = SvgSchemaInstance(id, schema)
        line_color = drawn.color.darker(PLACED_RING_DARKER)
        centers_y = {}
        label_pos = None
        if id in upper_rows:
            y = system.top() - unit * BAND_GAP_FACTOR - upper_rows[id] * upper_slot
            centers_y["upper"] = y - radius
            label_pos = ("above", centers_y["upper"])
        if id in lower_rows:
            top = system.bottom() + unit * BAND_GAP_FACTOR + lower_rows[id] * lower_slot
            centers_y["inner"] = top + radius
            centers_y["lower"] = top + radius + (circle_row if has_inner else 0)
            if label_pos is None:
                label_pos = ("below", centers_y["lower"])

        for placed in placed_by_id[id]:
            center = QPointF(x_of(placed), centers_y[placed["voice"]])
            drawn.degrees.append(
                SvgSchemaDegree(
                    id, placed, center, radius, drawn.color, on_press, on_double_click
                )
            )
            # A ring around the notehead, wider for each instance sharing it.
            k = halos_on.get(placed["notehead"], 0)
            halos_on[placed["notehead"]] = k + 1
            margin = unit * (HALO_MARGIN_FACTOR + k * HALO_STEP_FACTOR)
            halo = QGraphicsEllipseItem(
                noteheads[placed["notehead"]].adjusted(-margin, -margin, margin, margin)
            )
            halo.setPen(QPen(line_color, unit * HALO_WIDTH_FACTOR))
            halo.setBrush(Qt.BrushStyle.NoBrush)
            halo.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            halo.setZValue(Z_VALUE - 1)
            drawn.halos.append(halo)

        for voice in VOICES:
            in_voice = sorted(
                (d for d in drawn.degrees if d.placed["voice"] == voice),
                key=lambda d: (d.placed["stage"], d.placed["index"]),
            )
            if len(in_voice) < 2:
                continue
            path = QPainterPath(in_voice[0].pos())
            for degree in in_voice[1:]:
                path.lineTo(degree.pos())
            line = QGraphicsPathItem(path)
            line.setPen(
                QPen(
                    line_color,
                    unit * LINE_WIDTH_FACTOR,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            line.setZValue(Z_VALUE - 0.5)
            drawn.lines.append(line)

        if drawn.degrees and label_pos is not None:
            side, y = label_pos
            voices = ("upper",) if side == "above" else ("inner", "lower")
            left = (
                min(d.x() for d in drawn.degrees if d.placed["voice"] in voices)
                - radius
            )
            label = QGraphicsSimpleTextItem(schema["name"])
            label.setFont(font)
            label.setBrush(line_color)
            label.setPos(
                left, y - radius - label_height if side == "above" else y + radius
            )
            label.setZValue(Z_VALUE)
            drawn.label = label

        result[id] = drawn
    return result
