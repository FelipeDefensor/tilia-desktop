from PySide6.QtGui import QGuiApplication


# noinspection PyUnresolvedReferences
class CursorMixIn:
    def __init__(self, cursor_shape, *args, **kwargs):
        super().__init__(*args, *kwargs)
        self.cursor_shape = cursor_shape
        self._cursor_pushed = False
        self.setAcceptHoverEvents(True)

    def hoverEnterEvent(self, event) -> None:
        if not self._cursor_pushed:
            QGuiApplication.setOverrideCursor(self.cursor_shape)
            self._cursor_pushed = True
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        if self._cursor_pushed:
            QGuiApplication.restoreOverrideCursor()
            self._cursor_pushed = False
        super().hoverLeaveEvent(event)

    def cleanup(self):
        # The item may be hidden or removed while hovered (e.g. a whisker
        # collapsing when its frame extremity is dragged onto the body).
        # In that case Qt sends no hoverLeaveEvent, so the override cursor
        # would otherwise stay on the stack.
        if self._cursor_pushed:
            QGuiApplication.restoreOverrideCursor()
            self._cursor_pushed = False
