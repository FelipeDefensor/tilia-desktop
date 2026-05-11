from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QMouseEvent,
    QPainter,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsProxyWidget,
    QGraphicsScene,
    QGraphicsView,
    QSizePolicy,
)

from tilia.requests import Get, Post, get, listen, post
from tilia.settings import settings


class TimelineView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene):
        super().__init__()
        self.setScene(scene)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(int(scene.height()))
        self.setFixedWidth(int(get(Get.TIMELINE_WIDTH)))

        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setBackgroundBrush(
            QBrush(QColor(settings.get("general", "timeline_background_color")))
        )
        # Hover-guideline needs move events without any button held.
        self.setMouseTracking(True)
        listen(
            self,
            Post.SETTINGS_UPDATED,
            self.on_settings_updated,
        )

        self.dragging = False
        self.proxy = QGraphicsProxyWidget()  # will be set by TimelineUIs

    def on_settings_updated(self, updated_settings):
        if "general" in updated_settings:
            self.setBackgroundBrush(
                QBrush(QColor(settings.get("general", "timeline_background_color")))
            )

    def _topmost_clickable_item(self, pos):
        # Decorative scene items (hover guideline, row highlight, joined-
        # range separator, row-divider HLines) set `ignore_right_click =
        # True` so they fall through to the underlying element. The flag
        # name is historical — we honour it for *all* click types now,
        # because the live hover line revealed the same gap on the left-
        # click path: when the hover line happened to be the topmost
        # visible item (e.g. above a level-2+ hierarchy whose body sits
        # at z=-2 vs. hover_line's z=-1, or over empty timeline space),
        # `itemAt` returned the hover line and the click never reached
        # the element underneath. Walk the items list in stacking order
        # (front-to-back) and return the first one that wants the click.
        for item in self.items(pos):
            if not getattr(item, "ignore_right_click", False):
                return item
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        def handle_left_click():
            self.dragging = True
            post(
                Post.TIMELINE_VIEW_LEFT_CLICK,
                self,
                event.pos().x(),
                event.pos().y(),
                self._topmost_clickable_item(event.pos()),
                QGuiApplication.keyboardModifiers(),
                double=False,
            )

        def handle_right_click():
            post(
                Post.TIMELINE_VIEW_RIGHT_CLICK,
                self,
                self.mapToGlobal(event.pos()).x(),
                self.mapToGlobal(event.pos()).y(),
                self._topmost_clickable_item(event.pos()),
                QGuiApplication.keyboardModifiers(),
                double=False,
            )

        if event.button() == Qt.MouseButton.LeftButton:
            handle_left_click()
        elif event.button() == Qt.MouseButton.RightButton:
            handle_right_click()

        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            post(
                Post.TIMELINE_VIEW_DOUBLE_LEFT_CLICK,
                self,
                event.pos().x(),
                event.pos().y(),
                self._topmost_clickable_item(event.pos()),
                QGuiApplication.keyboardModifiers(),
                double=True,
            )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self.dragging:
            self.dragging = False
            post(Post.TIMELINE_VIEW_LEFT_BUTTON_RELEASE)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        post(Post.TIMELINE_VIEW_LEFT_BUTTON_DRAG, event.pos().x(), event.pos().y())
        post(Post.TIMELINE_VIEW_HOVER, event.pos().x())

        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        post(Post.TIMELINE_VIEW_HOVER, None)
        super().leaveEvent(event)

    def set_height(self, value):
        self.setFixedHeight(value)

    def set_is_visible(self, value):
        self.show() if value else self.hide()

    def keyPressEvent(self, event) -> None:
        ctrl = Qt.KeyboardModifier.ControlModifier in event.modifiers()
        key = event.key()
        if ctrl and key == Qt.Key.Key_Up:
            post(Post.TIMELINE_KEY_PRESS_CTRL_UP)
        elif ctrl and key == Qt.Key.Key_Down:
            post(Post.TIMELINE_KEY_PRESS_CTRL_DOWN)
        else:
            request = {
                Qt.Key.Key_Right: Post.TIMELINE_KEY_PRESS_RIGHT,
                Qt.Key.Key_Left: Post.TIMELINE_KEY_PRESS_LEFT,
                Qt.Key.Key_Up: Post.TIMELINE_KEY_PRESS_UP,
                Qt.Key.Key_Down: Post.TIMELINE_KEY_PRESS_DOWN,
            }.get(key, None)
            if request:
                post(request)

        super().keyPressEvent(event)
