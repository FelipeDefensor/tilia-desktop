"""Draws a schema as stages of degree circles, one row per voice.

The same circles are dragged from the diagram onto the score, so painting
them lives here and is shared with the score viewer.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QDrag,
    QFont,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from tilia.timelines.score.schema import DEGREE_VALUES, VOICES, degree_label

DEGREE_MIME_TYPE = "application/x-tilia-schema-degree"

# Fill and text colors of the degree circles, by voice: black, silver and
# white from top to bottom, as in NoghenMadid.
VOICE_COLORS = {
    "upper": (QColor("black"), QColor("white")),
    "inner": (QColor("silver"), QColor("black")),
    "lower": (QColor("white"), QColor("black")),
}
VOICE_NAMES = {"upper": "Upper", "inner": "Inner voices", "lower": "Bass"}
DEGREE_RADIUS = 11
PLACED_RING_WIDTH = 3
# Schema colors are pastel: darken the ring so it shows on white.
PLACED_RING_DARKER = 160
LINE_WIDTH = 2
FRAME_WIDTH = 2
FRAME_RADIUS = 8


def paint_degree(
    painter: QPainter,
    center: QPointF,
    radius: float,
    voice: str,
    label: str,
    ring_color: QColor | None = None,
) -> None:
    """A degree circle. `ring_color` draws a thick ring around it instead of
    the thin black outline."""
    fill, text = VOICE_COLORS[voice]
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if ring_color is not None:
        painter.setPen(QPen(ring_color, PLACED_RING_WIDTH))
    else:
        painter.setPen(QPen(QColor("black"), 1.5))
    painter.setBrush(fill)
    painter.drawEllipse(center, radius, radius)

    font = QFont(painter.font())
    font.setPixelSize(max(8, round(radius * (0.9 if len(label) < 2 else 0.75))))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(text)
    rect = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
    painter.restore()


def degree_mime_data(
    schema_name: str, stage: int, voice: str, index: int, degree: dict
) -> QMimeData:
    mime = QMimeData()
    payload = {
        "schema": schema_name,
        "stage": stage,
        "voice": voice,
        "index": index,
        "value": degree["value"],
        "accidental": degree.get("accidental", "="),
    }
    mime.setData(DEGREE_MIME_TYPE, QByteArray(json.dumps(payload).encode()))
    return mime


def read_degree_mime_data(mime: QMimeData) -> dict | None:
    if not mime.hasFormat(DEGREE_MIME_TYPE):
        return None
    try:
        return json.loads(bytes(mime.data(DEGREE_MIME_TYPE)).decode())
    except ValueError:
        return None


class SchemaDiagram(QWidget):
    """A schema's stages, left to right, with the degrees of each voice joined
    by lines. Higher degrees are drawn higher within their voice's row.

    With `draggable`, each circle can be dragged out (onto the score viewer)
    as DEGREE_MIME_TYPE data.
    """

    def __init__(self, draggable: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.schema: dict | None = None
        self.placed: set[tuple[int, str, int]] = set()
        self.draggable = draggable
        self._press_pos: QPoint | None = None
        self._pressed: tuple[int, str, int] | None = None
        self.setMinimumSize(220, 150)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )

    def sizeHint(self) -> QSize:
        return QSize(320, 180)

    def set_schema(self, schema: dict | None) -> None:
        self.schema = schema
        self.placed = set()
        self.update()

    def set_placed(self, placed: set[tuple[int, str, int]]) -> None:
        """Marks the degrees (stage, voice, index) already placed on the score."""
        self.placed = placed
        self.update()

    def _voices_shown(self) -> list[str]:
        """The voices with degrees, so a two-voice schema uses the whole height."""
        if not self.schema:
            return []
        return [
            v for v in VOICES if any(stage.get(v) for stage in self.schema["stages"])
        ]

    def degree_center(self, stage: int, voice: str, index: int) -> QPointF | None:
        if not self.schema:
            return None
        stages = self.schema["stages"]
        voices = self._voices_shown()
        if not (0 <= stage < len(stages)) or voice not in voices:
            return None
        degrees = stages[stage].get(voice, [])
        if not (0 <= index < len(degrees)):
            return None

        step_x = self.width() / (len(stages) + 1)
        row_height = self.height() / len(voices)
        row_top = voices.index(voice) * row_height
        margin = DEGREE_RADIUS + FRAME_WIDTH
        span = max(1.0, row_height - 2 * margin)
        value = degrees[index]["value"]
        y = (
            row_top
            + margin
            + span
            * (max(DEGREE_VALUES) - value)
            / (max(DEGREE_VALUES) - min(DEGREE_VALUES))
        )
        # Several degrees of one voice in a stage sit side by side.
        x = step_x * (stage + 1) + (index - (len(degrees) - 1) / 2) * (
            2 * DEGREE_RADIUS + 2
        )
        return QPointF(x, y)

    def degrees(self) -> list[tuple[int, str, int]]:
        if not self.schema:
            return []
        return [
            (s, voice, i)
            for s, stage in enumerate(self.schema["stages"])
            for voice in self._voices_shown()
            for i in range(len(stage.get(voice, [])))
        ]

    def degree_at(self, pos: QPointF) -> tuple[int, str, int] | None:
        for key in self.degrees():
            center = self.degree_center(*key)
            if (center - pos).manhattanLength() <= 1.5 * DEGREE_RADIUS:
                return key
        return None

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.schema:
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "No schema selected"
            )
            return

        color = QColor(self.schema.get("color") or "black")
        painter.setPen(QPen(color, FRAME_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(1, 1, -1, -1), FRAME_RADIUS, FRAME_RADIUS
        )

        # Lines first, joining each voice's first degree from stage to stage.
        painter.setPen(QPen(QColor("black"), LINE_WIDTH))
        for voice in self._voices_shown():
            points = [
                self.degree_center(s, voice, 0)
                for s, stage in enumerate(self.schema["stages"])
                if stage.get(voice)
            ]
            for a, b in zip(points, points[1:], strict=False):
                painter.drawLine(a, b)

        for key in self.degrees():
            stage, voice, index = key
            degree = self.schema["stages"][stage][voice][index]
            paint_degree(
                painter,
                self.degree_center(*key),
                DEGREE_RADIUS,
                voice,
                degree_label(degree["value"], degree.get("accidental", "=")),
                ring_color=color.darker(PLACED_RING_DARKER)
                if key in self.placed
                else None,
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.draggable and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = self.degree_at(event.position())
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._pressed is not None
            and (event.position().toPoint() - self._press_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            pressed, self._pressed = self._pressed, None
            self.start_drag(*pressed)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._pressed = None
        super().mouseReleaseEvent(event)

    def drag_pixmap(self, stage: int, voice: str, index: int) -> QPixmap:
        degree = self.schema["stages"][stage][voice][index]
        size = 2 * DEGREE_RADIUS + 4
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        paint_degree(
            painter,
            QPointF(size / 2, size / 2),
            DEGREE_RADIUS,
            voice,
            degree_label(degree["value"], degree.get("accidental", "=")),
        )
        painter.end()
        return pixmap

    def start_drag(self, stage: int, voice: str, index: int) -> None:
        degree = self.schema["stages"][stage][voice][index]
        drag = QDrag(self)
        drag.setMimeData(
            degree_mime_data(self.schema["name"], stage, voice, index, degree)
        )
        pixmap = self.drag_pixmap(stage, voice, index)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        drag.exec(Qt.DropAction.CopyAction)
