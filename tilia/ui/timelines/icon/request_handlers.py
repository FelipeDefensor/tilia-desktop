from __future__ import annotations

from typing import TYPE_CHECKING

from tilia.requests import Post, get, Get
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.icon.enums import Alignment
from tilia.timelines.timeline_kinds import TimelineKind
from tilia.ui.timelines.base.request_handlers import TimelineUIRequestHandler, ElementRequestHandler
from tilia.ui.timelines.copy_paste import get_copy_data_from_element
from tilia.ui.timelines.icon import IconUI

if TYPE_CHECKING:
    from tilia.ui.timelines.icon import IconTimelineUI


class IconTimelineUIRequestHandler(ElementRequestHandler):
    def __init__(self, timeline_ui: IconTimelineUI):

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
            ComponentKind.ICON, get(Get.SELECTED_TIME), 'DotMid', Alignment.CENTER
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
                        elm, IconUI.DEFAULT_COPY_ATTRIBUTES
                    ),
                    "timeline_kind": TimelineKind.ICON_TIMELINE,
                }
            )

        return copy_data
