from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter, QPen
from PySide6.QtPdfWidgets import QPdfView

from tilia.ui.windows.view_window import ViewWindow

REGION_COLOR = QColor(30, 110, 220)
ACTIVE_REGION_COLOR = QColor(240, 130, 0)
ACTIVE_REGION_FILL_ALPHA = 50
REGION_PEN_WIDTH = 2
# Drags shorter than this (in pixels, on both axes) are treated as clicks.
MIN_REGION_DRAG = 5
# Space left above the active region when scrolling to it, in page points.
SCROLL_MARGIN = 20


@dataclass
class PdfRegion:
    page_number: int  # 1-based
    bbox: list[float]  # [x, y, width, height], relative to the page size
    is_active: bool = False


class QPdfWindow(ViewWindow, QPdfView):
    """
    PDF viewer that draws page regions over the rendered pages and lets the
    user draw new ones by dragging with the left mouse button.

    QPdfView does not expose where it lays out pages, so `page_rect()`
    reproduces its layout: pages stacked vertically, scaled by screen
    resolution and zoom factor, and centered horizontally.
    """

    def __init__(self, name: str):
        super().__init__("TiLiA PDF Viewer", None, menu_title=name)
        self.setPageMode(QPdfView.PageMode.MultiPage)
        self.regions: list[PdfRegion] = []
        self.on_region_drawn: Callable[[int, list[float]], None] | None = None
        self._drag_start: QPoint | None = None
        self._drag_rect: QRect | None = None

    def update_window(self, width: int, height: int):
        self.resize(width, height)
        self.show()

    def set_regions(self, regions: list[PdfRegion]) -> None:
        self.regions = regions
        self.viewport().update()

    def _page_pixel_sizes(self) -> list[QSize]:
        document = self.document()
        if not document:
            return []
        scale = (
            QGuiApplication.primaryScreen().logicalDotsPerInch()
            / 72.0
            * self.zoomFactor()
        )
        return [
            (document.pagePointSize(page) * scale).toSize()
            for page in range(document.pageCount())
        ]

    def page_rect(self, page_number: int) -> QRectF | None:
        """Rect of a 1-based page in viewport coordinates."""
        sizes = self._page_pixel_sizes()
        if not 1 <= page_number <= len(sizes):
            return None

        margins = self.documentMargins()
        total_width = max(size.width() for size in sizes)
        document_width = total_width + margins.left() + margins.right()
        x_offset = max(0, (self.viewport().width() - document_width) // 2)

        y = margins.top()
        for size in sizes[: page_number - 1]:
            y += size.height() + self.pageSpacing()

        size = sizes[page_number - 1]
        x = margins.left() + (total_width - size.width()) // 2 + x_offset
        return QRectF(
            x - self.horizontalScrollBar().value(),
            y - self.verticalScrollBar().value(),
            size.width(),
            size.height(),
        )

    def page_at(self, point: QPointF) -> int | None:
        for page_number in range(1, len(self._page_pixel_sizes()) + 1):
            rect = self.page_rect(page_number)
            if rect.contains(point):
                return page_number
        return None

    def region_rect(self, region: PdfRegion) -> QRectF | None:
        page = self.page_rect(region.page_number)
        if page is None:
            return None
        x, y, w, h = region.bbox
        return QRectF(
            page.x() + x * page.width(),
            page.y() + y * page.height(),
            w * page.width(),
            h * page.height(),
        )

    def scroll_to_region(self, region: PdfRegion) -> None:
        document = self.document()
        page_height = document.pagePointSize(region.page_number - 1).height()
        top = max(0.0, region.bbox[1] * page_height - SCROLL_MARGIN)
        self.pageNavigator().jump(region.page_number - 1, QPointF(0, top), 0)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for region in self.regions:
            rect = self.region_rect(region)
            if rect is None:
                continue
            color = ACTIVE_REGION_COLOR if region.is_active else REGION_COLOR
            painter.setPen(QPen(color, REGION_PEN_WIDTH))
            if region.is_active:
                fill = QColor(color)
                fill.setAlpha(ACTIVE_REGION_FILL_ALPHA)
                painter.setBrush(fill)
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)

        if self._drag_rect is not None:
            painter.setPen(QPen(REGION_COLOR, 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._drag_rect)

        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self._drag_rect = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_start is not None:
            self._drag_rect = QRect(
                self._drag_start, event.position().toPoint()
            ).normalized()
            self.viewport().update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            self._finish_drag(self._drag_start, event.position().toPoint())
            self._drag_start = None
            self._drag_rect = None
            self.viewport().update()
        super().mouseReleaseEvent(event)

    def _finish_drag(self, start: QPoint, end: QPoint) -> None:
        if (
            abs(end.x() - start.x()) < MIN_REGION_DRAG
            or abs(end.y() - start.y()) < MIN_REGION_DRAG
        ):
            return

        page_number = self.page_at(QPointF(start))
        if page_number is None:
            return

        page = self.page_rect(page_number)
        drawn = QRectF(QPointF(start), QPointF(end)).normalized().intersected(page)
        if drawn.isEmpty():
            return

        bbox = [
            (drawn.x() - page.x()) / page.width(),
            (drawn.y() - page.y()) / page.height(),
            drawn.width() / page.width(),
            drawn.height() / page.height(),
        ]
        # Guard against float error pushing the rect past the page edge.
        bbox[2] = min(bbox[2], 1 - bbox[0])
        bbox[3] = min(bbox[3], 1 - bbox[1])

        if self.on_region_drawn:
            self.on_region_drawn(page_number, bbox)
