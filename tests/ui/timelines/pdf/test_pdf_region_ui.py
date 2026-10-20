import pytest
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtTest import QTest

from tests.ui.timelines.pdf.test_pdf_marker_ui import get_inspect_widget
from tests.utils import get_command_action, save_and_reopen, undoable
from tilia.requests import Post, post
from tilia.timelines.pdf.timeline import PdfTimeline
from tilia.ui import commands
from tilia.ui.timelines.pdf import PdfTimelineUI
from tilia.ui.timelines.pdf.context_menu import PdfMarkerContextMenu
from tilia.ui.timelines.pdf.viewer import SCROLL_MARGIN
from tilia.ui.windows import WindowKind

REGION = [0.1, 0.2, 0.5, 0.25]


def set_region(tlui, page_number=1, bbox=None, **kwargs):
    commands.execute(
        "timeline.pdf.set_region",
        timeline_id=tlui.id,
        page_number=page_number,
        bbox=bbox or REGION,
        **kwargs,
    )


def drag_in_viewer(viewer, start: QPoint, end: QPoint):
    viewport = viewer.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(viewport, end)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)


def page_point(viewer, page_number: int, x: float, y: float) -> QPoint:
    rect = viewer.page_rect(page_number)
    return QPoint(
        round(rect.x() + x * rect.width()), round(rect.y() + y * rect.height())
    )


class TestSetRegion:
    def test_creates_marker_at_current_time(self, pdf_tlui):
        commands.execute("media.seek", 10)

        with undoable():
            set_region(pdf_tlui, page_number=1)

        assert len(pdf_tlui) == 1
        assert pdf_tlui[0].get_data("time") == 10
        assert pdf_tlui[0].get_data("page_number") == 1
        assert pdf_tlui[0].get_data("bbox") == REGION

    def test_updates_selected_marker(self, pdf_tlui, pdf_tl):
        pdf_tl.page_total = 2
        commands.execute("timeline.pdf.add", time=0, page_number=1)
        commands.execute("media.seek", 10)
        pdf_tlui.select_element(pdf_tlui[0])

        with undoable():
            set_region(pdf_tlui, page_number=2)

        assert len(pdf_tlui) == 1
        assert pdf_tlui[0].get_data("page_number") == 2
        assert pdf_tlui[0].get_data("bbox") == REGION

    def test_updates_marker_at_current_time(self, pdf_tlui):
        commands.execute("timeline.pdf.add", time=10, page_number=1)
        commands.execute("media.seek", 10)

        set_region(pdf_tlui)

        assert len(pdf_tlui) == 1
        assert pdf_tlui[0].get_data("bbox") == REGION

    def test_only_affects_target_timeline(self, pdf_tlui, tls, tluis, resources):
        other_tl = tls.create_timeline(
            PdfTimeline, path=str((resources / "example.pdf").resolve())
        )
        other_tl.clear()
        other_tlui = tluis.get_timeline_ui(other_tl.id)

        set_region(other_tlui)

        assert len(pdf_tlui) == 0
        assert len(other_tlui) == 1

    @pytest.mark.parametrize(
        "bbox",
        [[-0.1, 0, 0.5, 0.5], [0.6, 0, 0.5, 0.5], [0, 0, 0, 0.5], [0, 0, 0.5]],
    )
    def test_invalid_region_is_rejected(self, pdf_tlui, bbox):
        commands.execute("timeline.pdf.add", time=0, bbox=bbox)
        assert len(pdf_tlui) == 0

    def test_marker_without_region_points_to_whole_page(self, pdf_tlui):
        commands.execute("timeline.pdf.add", time=0)
        assert pdf_tlui[0].get_data("bbox") is None

    def test_region_survives_save_and_reopen(self, pdf_tlui, tluis, tmp_path):
        set_region(pdf_tlui)

        save_and_reopen(tmp_path)

        reloaded = [t for t in tluis if isinstance(t, PdfTimelineUI)][0]
        assert reloaded[0].get_data("bbox") == REGION


class TestClearRegion:
    def test_context_menu_has_clear_region(self, pdf_tlui):
        set_region(pdf_tlui)
        menu = PdfMarkerContextMenu(pdf_tlui[0])
        assert get_command_action(menu, "timeline.pdf.clear_region")

    def test_clear_region_from_context_menu(self, pdf_tlui):
        set_region(pdf_tlui)
        pdf_tlui.select_element(pdf_tlui[0])
        menu = PdfMarkerContextMenu(pdf_tlui[0])

        with undoable():
            get_command_action(menu, "timeline.pdf.clear_region").trigger()

        assert pdf_tlui[0].get_data("bbox") is None
        assert pdf_tlui.pdf_view.regions == []


class TestCopyPaste:
    def test_region_is_pasted_into_selected_marker(self, pdf_tlui):
        set_region(pdf_tlui, time=0)
        commands.execute("timeline.pdf.add", time=10, page_number=1)
        pdf_tlui.select_element(pdf_tlui[0])
        commands.execute("timeline.component.copy")
        pdf_tlui.deselect_element(pdf_tlui[0])
        pdf_tlui.select_element(pdf_tlui[1])

        with undoable():
            commands.execute("timeline.component.paste")

        assert pdf_tlui[1].get_data("bbox") == REGION


class TestInspect:
    @pytest.fixture(autouse=True)
    def close_inspector(self):
        yield
        post(Post.WINDOW_CLOSE, WindowKind.INSPECT)

    def test_inspector_shows_region(self, pdf_tlui, qtui):
        set_region(pdf_tlui)
        pdf_tlui.select_element(pdf_tlui[0])
        commands.execute("timeline.element.inspect")

        assert get_inspect_widget(qtui, "Region").text() == "50% × 25% at (10%, 20%)"

    def test_inspector_shows_whole_page(self, pdf_tlui, qtui):
        commands.execute("timeline.pdf.add", time=0)
        pdf_tlui.select_element(pdf_tlui[0])
        commands.execute("timeline.element.inspect")

        assert get_inspect_widget(qtui, "Region").text() == "Whole page"


class TestViewer:
    def test_drag_draws_region(self, pdf_tlui):
        viewer = pdf_tlui.pdf_view
        commands.execute("media.seek", 5)

        drag_in_viewer(
            viewer,
            page_point(viewer, 1, 0.1, 0.2),
            page_point(viewer, 1, 0.6, 0.45),
        )

        assert len(pdf_tlui) == 1
        assert pdf_tlui[0].get_data("time") == 5
        assert pdf_tlui[0].get_data("page_number") == 1
        assert pdf_tlui[0].get_data("bbox") == pytest.approx(REGION, abs=0.01)

    def test_drag_is_clipped_to_page(self, pdf_tlui):
        viewer = pdf_tlui.pdf_view
        page = viewer.page_rect(1)

        drag_in_viewer(
            viewer,
            page_point(viewer, 1, 0.5, 0.5),
            QPoint(round(page.right()) + 50, round(page.y() + 0.75 * page.height())),
        )

        x, y, w, h = pdf_tlui[0].get_data("bbox")
        assert x + w == pytest.approx(1, abs=0.01)
        assert (x, y, h) == pytest.approx((0.5, 0.5, 0.25), abs=0.01)

    def test_click_does_not_draw_region(self, pdf_tlui):
        viewer = pdf_tlui.pdf_view
        point = page_point(viewer, 1, 0.5, 0.5)

        drag_in_viewer(viewer, point, point + QPoint(2, 2))

        assert len(pdf_tlui) == 0

    def test_region_of_current_marker_is_active(self, pdf_tlui, pdf_tl):
        pdf_tl.page_total = 2
        set_region(pdf_tlui, page_number=1, bbox=[0, 0, 1, 0.5], time=0)
        set_region(pdf_tlui, page_number=1, bbox=[0, 0.5, 1, 0.5], time=10)

        commands.execute("media.seek", 12)

        regions = pdf_tlui.pdf_view.regions
        assert [r.bbox for r in regions if r.is_active] == [[0, 0.5, 1, 0.5]]
        assert len(regions) == 2

    def test_seeking_to_region_on_other_page_shows_that_page(self, pdf_tlui, pdf_tl):
        pdf_tl.page_total = 2
        commands.execute("timeline.pdf.add", time=0, page_number=1)
        set_region(pdf_tlui, page_number=2, time=10)

        commands.execute("media.seek", 10)

        assert pdf_tlui.current_page == 2

    def test_region_low_on_page_is_scrolled_into_view(self, pdf_tlui):
        viewer = pdf_tlui.pdf_view
        viewer.resize(700, 400)
        commands.execute("timeline.pdf.add", time=0, page_number=1)
        set_region(pdf_tlui, page_number=1, bbox=[0.1, 0.85, 0.5, 0.1], time=10)

        commands.execute("media.seek", 10)

        rect = viewer.region_rect(viewer.regions[0])
        assert QRectF(viewer.viewport().rect()).contains(rect)
        assert rect.top() == pytest.approx(SCROLL_MARGIN, abs=2)

    def test_visible_region_does_not_scroll(self, pdf_tlui):
        viewer = pdf_tlui.pdf_view
        set_region(pdf_tlui, page_number=1, bbox=[0.1, 0.05, 0.3, 0.1], time=0)
        set_region(pdf_tlui, page_number=1, bbox=[0.5, 0.05, 0.3, 0.1], time=10)
        commands.execute("media.seek", 1)
        scroll = viewer.verticalScrollBar().value()

        commands.execute("media.seek", 11)

        assert viewer.verticalScrollBar().value() == scroll
