from __future__ import annotations

from typing import TYPE_CHECKING

from tilia.requests import Post, get, Get
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.timeline_kinds import TimelineKind
from tilia.ui.color import get_tinted_color
from tilia.ui.consts import TINT_FACTOR_ON_SELECTION
from tilia.ui.timelines.base.request_handlers import ElementRequestHandler
from tilia.ui.timelines.copy_paste import get_copy_data_from_element
from tilia.ui.timelines.marker import MarkerUI

if TYPE_CHECKING:
    from tilia.ui.timelines.marker import MarkerTimelineUI


class MarkerUIRequestHandler(ElementRequestHandler):
    def __init__(self, timeline_ui: MarkerTimelineUI):

        super().__init__(
            timeline_ui,
            {
                Post.ICON_ADD: self.on_add,
                Post.ICON_DELETE: self.on_delete,
                Post.TIMELINE_ELEMENT_DELETE: self.on_delete,
                Post.TIMELINE_ELEMENT_COPY: self.on_copy,
                Post.TIMELINE_ELEMENT_PASTE: self.on_paste,
            },
        )

    def on_add(self, *_, **__):
        self.timeline.create_timeline_component(
            ComponentKind.ICON, get(Get.SELECTED_TIME)
        )

    def on_delete(self, elements, *_, **__):
        self.timeline.delete_components(self.elements_to_components(elements))

    @staticmethod
    def on_copy(elements):
        copy_data = []
        for elm in elements:
            copy_data.append(
                {
                    "components": get_copy_data_from_element(
                        elm, MarkerUI.DEFAULT_COPY_ATTRIBUTES
                    ),
                    "timeline_kind": TimelineKind.MARKER_TIMELINE,
                }
            )

        return copy_data
