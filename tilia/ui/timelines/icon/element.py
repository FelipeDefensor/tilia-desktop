from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QPen
from PyQt6.QtWidgets import (
    QGraphicsScene,
    QGraphicsItem,
    QGraphicsPixmapItem, QGraphicsRectItem,
)

from tilia.requests import Post, post, get, Get
from tilia.settings import settings
from tilia.timelines.icon.components import Icon
from tilia.timelines.icon.enums import Alignment
from tilia.ui.timelines.base.element import TimelineUIElement
from .context_menu import IconContextMenu
from tilia.ui.timelines.copy_paste import CopyAttributes
from tilia.ui.timelines.cursors import CursorMixIn
from tilia.ui.timelines.drag import DragManager
from tilia.ui.color import get_tinted_color
from tilia.ui.consts import TINT_FACTOR_ON_SELECTION
from tilia.ui.coords import get_x_by_time, get_time_by_x
from tilia.ui.format import format_media_time
from tilia.ui.windows.inspect import InspectRowKind

if TYPE_CHECKING:
    from .timeline import IconTimelineUI


class IconUI(TimelineUIElement):
    LABEL_MARGIN = 3

    INSPECTOR_FIELDS = [
        ("Time", InspectRowKind.LABEL, None),
        ("Icon", InspectRowKind.COMBO_BOX, lambda: {"items": [(name.capitalize(), name) for name in Icon.ICON_NAMES]}),
        ("Horizontal alignment", InspectRowKind.COMBO_BOX, lambda: {"items": [(x.name, Alignment(x)) for x in Alignment]}),
    ]

    FIELD_NAMES_TO_ATTRIBUTES = {"Time": "time", "Icon": "icon_name", "Horizontal alignment": "h_alignment"}

    DEFAULT_COPY_ATTRIBUTES = CopyAttributes(
        by_element_value=[],
        by_component_value=["icon_name", "h_alignment"],
        support_by_element_value=[],
        support_by_component_value=["time"],
    )

    UPDATE_TRIGGERS = ["time", "icon_name", "h_alignment"]

    CONTEXT_MENU_CLASS = IconContextMenu

    def __init__(
        self,
        id: int,
        timeline_ui: IconTimelineUI,
        scene: QGraphicsScene,
        **_,
    ):
        super().__init__(id=id, timeline_ui=timeline_ui, scene=scene)

        self._setup_body()

        self.dragged = False
        self.drag_manager = None

    def _setup_body(self):
        self.body = IconBody(self.x, self.get_data("h_alignment"), self.icon_path)
        self.scene.addItem(self.body)

    @property
    def x(self):
        return get_x_by_time(self.get_data("time"))

    @property
    def icon_path(self):
        return self.icon_name_to_path(self.get_data("icon_name"))

    @property
    def seek_time(self):
        return self.get_data("time")

    @property
    def height(self):
        return settings.get("icon_timeline", "icon_height")

    @property
    def default_color(self):
        return settings.get("icon_timeline", "default_color")

    @property
    def ui_color(self):
        base_color = self.get_data("color") or self.default_color
        return (
            base_color
            if not self.is_selected()
            else get_tinted_color(base_color, TINT_FACTOR_ON_SELECTION)
        )

    def icon_name_to_path(self, name):
        return str((Path(__file__).parent / "img" / f"{name}.svg").resolve())

    def update_position(self):
        self.body.set_position(self.x, self.get_data("h_alignment"))

    def update_h_alignment(self):
        self.update_position()

    def update_time(self):
        self.update_position()

    def update_icon_name(self):
        self.body.set_icon(self.icon_path)

    def child_items(self):
        return [self.body]

    def left_click_triggers(self) -> list[QGraphicsItem]:
        return [self.body]

    def on_left_click(self, _) -> None:
        self.setup_drag()

    def double_left_click_triggers(self):
        return [self.body]

    def on_double_left_click(self, _):
        if self.drag_manager:
            self.drag_manager.on_release()
            self.drag_manager = None
        post(Post.PLAYER_SEEK, self.seek_time)

    def setup_drag(self):
        self.drag_manager = DragManager(
            get_min_x=lambda: get(Get.LEFT_MARGIN_X),
            get_max_x=lambda: get(Get.RIGHT_MARGIN_X),
            before_each=self.before_each_drag,
            after_each=self.after_each_drag,
            on_release=self.on_drag_end,
        )

    def before_each_drag(self):
        if not self.dragged:
            post(Post.ELEMENT_DRAG_START)
            self.dragged = True

    def after_each_drag(self, drag_x: int):
        self.set_data("time", get_time_by_x(drag_x))

    def on_drag_end(self):
        if self.dragged:
            post(Post.APP_RECORD_STATE, "icon drag")
            post(Post.ELEMENT_DRAG_END)

        self.dragged = False

    def on_select(self) -> None:
        self.body.on_select()

    def on_deselect(self) -> None:
        self.body.on_deselect()

    def get_inspector_dict(self) -> dict:
        return {
            "Time": format_media_time(self.get_data("time")),
            "Icon": self.get_data("icon_name"),
            "Horizontal alignment": self.get_data("h_alignment"),
        }


class IconBody(CursorMixIn, QGraphicsPixmapItem):
    def __init__(self, x: float, alignment: Alignment, path: str):
        super().__init__(cursor_shape=Qt.CursorShape.PointingHandCursor)
        self.selection_box = QGraphicsRectItem(self)
        self.selection_box.setRect(self.boundingRect())
        self.selection_box.hide()
        self.set_icon(path)
        self.set_position(x, alignment)

    def _get_alignment_offset(self, alignment: Alignment):
        if alignment == Alignment.LEFT:
            return 0
        elif alignment == Alignment.RIGHT:
            return -self.pixmap.width()
        else:
            return -self.pixmap.width() / 2

    def set_icon(self, path: str):
        self.pixmap = QPixmap(path)
        self.setPixmap(self.pixmap)
        self.selection_box.setRect(self.boundingRect())

    def set_position(self, x, alignment: Alignment):
        self.setPos(x + self._get_alignment_offset(alignment), 0)

    def on_select(self):
        self.selection_box.show()

    def on_deselect(self):
        self.selection_box.hide()
