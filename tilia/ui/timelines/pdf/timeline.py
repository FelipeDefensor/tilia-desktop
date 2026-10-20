from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF
from PySide6.QtPdf import QPdfDocument

import tilia.errors
from tilia.media.player.base import MediaTimeChangeReason
from tilia.requests import Get, Post, get, listen
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.pdf.timeline import PdfTimeline
from tilia.ui import commands
from tilia.ui.menus import PdfMenu
from tilia.ui.timelines.base.timeline import (
    TimelineUI,
)
from tilia.ui.timelines.collection.collection import TimelineSelector, TimelineUIs
from tilia.ui.timelines.copy_paste import (
    paste_into_element,
)
from tilia.ui.timelines.pdf.context_menu import PdfTimelineUIContextMenu
from tilia.ui.timelines.pdf.element import PdfMarkerUI
from tilia.ui.timelines.pdf.toolbar import PdfTimelineToolbar
from tilia.ui.timelines.pdf.viewer import PdfRegion, QPdfWindow

if TYPE_CHECKING:
    from tilia.ui.timelines.base.element_manager import ElementManager
    from tilia.ui.timelines.scene import TimelineScene
    from tilia.ui.timelines.view import TimelineView


class PdfTimelineUI(TimelineUI):
    CONTEXT_MENU_CLASS = PdfTimelineUIContextMenu
    TOOLBAR_CLASS = PdfTimelineToolbar
    ELEMENT_CLASS = PdfMarkerUI
    ACCEPTS_HORIZONTAL_ARROWS = True
    timeline_class = PdfTimeline
    menu_class = PdfMenu

    def __init__(
        self,
        id: int,
        collection: TimelineUIs,
        element_manager: ElementManager,
        scene: TimelineScene,
        view: TimelineView,
    ):
        super().__init__(id, collection, element_manager, scene, view)

        self._setup_pdf_document()
        self._load_pdf_file()

        listen(self, Post.PLAYER_CURRENT_TIME_CHANGED, self.on_media_time_change)

    @classmethod
    def get_additional_args_for_creation(cls):
        success, path = get(Get.FROM_USER_PDF_PATH)
        return success, {"path": path}

    def _handle_invalid_pdf(self):
        tilia.errors.display(tilia.errors.INVALID_PDF, self.get_data("path"))
        confirm = get(Get.FROM_USER_RETRY_PDF_PATH)
        if confirm:
            success, path = get(Get.FROM_USER_PDF_PATH)
            if success:
                self.timeline.set_data("path", path)
                self._load_pdf_file()

    def _load_pdf_file(self):
        if not self.timeline.get_data("is_pdf_valid"):
            self._handle_invalid_pdf()
        self.pdf_document.load(self.get_data("path"))
        self.pdf_view.update_window(
            int(self.pdf_document.pagePointSize(0).height()),
            int(self.pdf_document.pagePointSize(0).width()),
        )

    def _setup_pdf_document(self):
        self.pdf_document = QPdfDocument(None)
        self.pdf_view = QPdfWindow(self.get_data("name"))
        self.pdf_view.setDocument(self.pdf_document)
        self.pdf_view.on_region_drawn = self.on_region_drawn
        self._shown_marker_id: int | None = None

    def update_name(self):
        name = self.get_data("name")
        self.scene.set_text(name)
        self.pdf_view.update_title(name)

    @property
    def current_page(self):
        return self.pdf_view.pageNavigator().currentPage() + 1  # 1-based

    @property
    def page_total(self):
        if not self.timeline.get_data("is_pdf_valid"):
            # Lifts page number limit on Inspector. This
            # prevents it from capping the
            # number at a value that might be lower than
            # the page total in a PDF loaded in the future.
            # Can't use math.inf because pyside requires an int.
            return 99999999
        return self.timeline.get_data("page_total")

    @classmethod
    def register_commands(cls, collection: TimelineUIs):
        cls.register_timeline_command(
            collection,
            "add",
            cls.on_add,
            TimelineSelector.FIRST,
            text="Add PDF marker",
            shortcut="p",
            icon="pdf-add",
        )
        cls.register_timeline_command(
            collection,
            "set_region",
            cls.on_set_region,
            TimelineSelector.ALL,
            text="Set PDF region",
        )
        cls.register_timeline_command(
            collection,
            "clear_region",
            cls.on_clear_region,
            TimelineSelector.SELECTED,
            text="Clear PDF region",
        )

    def on_add(
        self,
        time: float | None = None,
        page_number: int | None = None,
        bbox: list[float] | None = None,
    ):
        if time is None:
            time = get(Get.SELECTED_TIME)

        # If no page number is provided, use next available page number
        requested_page_number = (
            page_number
            if page_number is not None
            else self.timeline.get_previous_page_number(time) + 1
        )

        # Clamp page number to valid range
        page_number = min(max(requested_page_number, 1), self.timeline.page_total)

        pdf_marker, reason = self.timeline.create_component(
            ComponentKind.PDF_MARKER, time, page_number, bbox=bbox
        )
        if not pdf_marker:
            tilia.errors.display(tilia.errors.ADD_PDF_MARKER_FAILED, reason)
            return False
        return True

    def on_region_drawn(self, page_number: int, bbox: list[float]) -> None:
        commands.execute(
            "timeline.pdf.set_region",
            timeline_id=self.id,
            page_number=page_number,
            bbox=bbox,
        )

    def on_set_region(
        self,
        timeline_id: int,
        page_number: int,
        bbox: list[float],
        time: float | None = None,
    ) -> bool:
        """
        Points a marker to a region of a page. Updates the selected marker if
        exactly one is selected, the marker at `time` if there is one, and
        otherwise creates a marker at `time` (defaults to the current media time).
        """
        if timeline_id != self.id:
            # Registered with TimelineSelector.ALL so drawing in a viewer can
            # target its own timeline; other PDF timelines are left untouched.
            return True

        if time is None:
            time = get(Get.MEDIA_CURRENT_TIME)

        selected = self.element_manager.get_selected_elements()
        if len(selected) == 1:
            target = selected[0]
        else:
            target = next(
                (e for e in self if e.get_data("time") == time),
                None,
            )

        if target is None:
            return self.on_add(time=time, page_number=page_number, bbox=bbox)

        target.set_data("page_number", page_number)
        target.set_data("bbox", bbox)
        return True

    def on_clear_region(self) -> bool:
        for element in self.element_manager.get_selected_elements():
            element.set_data("bbox", None)
        return True

    def on_timeline_component_created(
        self, kind: ComponentKind, id: int, get_data, set_data
    ):
        super().on_timeline_component_created(kind, id, get_data, set_data)
        self.update_displayed_page(get(Get.MEDIA_CURRENT_TIME))

    def on_timeline_component_deleted(self, id: int):
        super().on_timeline_component_deleted(id)
        self.update_displayed_page(get(Get.MEDIA_CURRENT_TIME))

    def _deselect_all_but_last(self):
        if len(self.selected_elements) > 1:
            for element in self.selected_elements[:-1]:
                self.element_manager.deselect_element(element)

    def paste_single_into_selected_elements(self, paste_data: list[dict] | dict):
        for element in self.element_manager.get_selected_elements():
            self.deselect_element(element)
            paste_into_element(element, paste_data[0])
            self.select_element(element)

    def paste_multiple_into_selected_elements(self, paste_data: list[dict] | dict):
        paste_data = sorted(paste_data, key=lambda md: md["context"]["time"])

        first_selected_element = self.selected_elements[0]

        self.deselect_element(self.selected_elements[0])
        paste_into_element(first_selected_element, paste_data[0])
        self.select_element(first_selected_element)

        self.create_pasted_markers(
            paste_data[1:],
            paste_data[0]["context"]["time"],
            self.selected_elements[0].get_data("time"),
        )

    def paste_single_into_timeline(self, paste_data: list[dict] | dict):
        return self.paste_multiple_into_timeline(paste_data)

    def paste_multiple_into_timeline(self, paste_data: list[dict] | dict):
        reference_time = min(md["context"]["time"] for md in paste_data)

        self.create_pasted_markers(
            paste_data,
            reference_time,
            get(Get.SELECTED_TIME),
        )

    def create_pasted_markers(
        self, paste_data: list[dict], reference_time: float, target_time: float
    ) -> None:
        for pdf_marker_data in copy.deepcopy(paste_data):
            # deepcopying so popping won't affect original data
            marker_time = pdf_marker_data["context"].pop("time")

            self.timeline.create_component(
                ComponentKind.PDF_MARKER,
                target_time + (marker_time - reference_time),
                **pdf_marker_data["values"],
                **pdf_marker_data["context"],
            )

    def on_media_time_change(self, time, reason: MediaTimeChangeReason) -> None:
        self.update_displayed_page(time)

    def update_displayed_page(self, time):
        current_marker = self.timeline.get_previous_component_by_time(time)
        self.update_regions(current_marker.id if current_marker else None)

        if current_marker and current_marker.get_data("bbox"):
            if self._shown_marker_id != current_marker.id:
                self.pdf_view.scroll_to_region(
                    PdfRegion(
                        current_marker.get_data("page_number"),
                        current_marker.get_data("bbox"),
                    )
                )
            self._shown_marker_id = current_marker.id
            return

        self._shown_marker_id = current_marker.id if current_marker else None
        target_page = self.timeline.get_previous_page_number(time)
        if target_page == 0:
            # No markers are present
            target_page = 1
        if self.pdf_view.pageNavigator().currentPage() != target_page - 1:
            self.pdf_view.pageNavigator().jump(target_page - 1, QPointF(0, 0), 0)

    def update_regions(self, active_marker_id: int | None) -> None:
        self.pdf_view.set_regions(
            [
                PdfRegion(
                    element.get_data("page_number"),
                    element.get_data("bbox"),
                    is_active=element.id == active_marker_id,
                )
                for element in self
                if element.get_data("bbox")
            ]
        )

    def delete(self):
        super().delete()
        self.pdf_view.deleteLater()
