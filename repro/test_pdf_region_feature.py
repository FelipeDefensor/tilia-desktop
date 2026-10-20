"""Headless acceptance checks for PDF marker regions (scenario S0).

Opens repro/pdf-region.tla (built by repro/build_pdf_region_fixture.py) and
goes through the same commands and viewer events the GUI uses. Run from the
repo root:

    uv run --python 3.12 python -m pytest -p tests.conftest -p no:xdist repro/test_pdf_region_feature.py -v

On feat/pdf-marker-bbox everything passes. On dev every test errors with
"set_region command not registered", which shows the feature isn't there.
"""

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from tests.utils import get_command_action, save_and_reopen, undoable
from tilia.timelines.pdf.timeline import PdfTimeline
from tilia.ui import commands

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "pdf-region.tla"

# Mirrors build_pdf_region_fixture.expected_markers(): 8 systems, 10 s each,
# 4 per page.
SECONDS_PER_SYSTEM = 10
SYSTEMS_PER_PAGE = 4


@pytest.fixture(autouse=True)
def require_feature(tluis):
    assert FIXTURE.exists(), "run repro/build_pdf_region_fixture.py first"
    assert (
        "timeline.pdf.set_region" in commands._name_to_callback
    ), "set_region command not registered (are you on dev?)"


@pytest.fixture
def pdf_tlui(tluis):
    commands.execute("file.open", str(FIXTURE))
    return next(t for t in tluis if isinstance(t.timeline, PdfTimeline))


def active_regions(tlui):
    return [r for r in tlui.pdf_view.regions if r.is_active]


def drag(viewer, page_number, start, end):
    rect = viewer.page_rect(page_number)

    def to_point(xy):
        return QPoint(
            round(rect.x() + xy[0] * rect.width()),
            round(rect.y() + xy[1] * rect.height()),
        )

    viewport = viewer.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=to_point(start))
    QTest.mouseMove(viewport, to_point(end))
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=to_point(end))


def test_fixture_loads_with_regions(pdf_tlui):
    assert len(pdf_tlui) == 8
    assert all(m.get_data("bbox") for m in pdf_tlui)
    assert len(pdf_tlui.pdf_view.regions) == 8


@pytest.mark.parametrize("system", range(8))
def test_playback_highlights_current_system(pdf_tlui, system):
    commands.execute("media.seek", system * SECONDS_PER_SYSTEM + 5)

    (active,) = active_regions(pdf_tlui)
    marker = pdf_tlui[system]
    assert active.bbox == marker.get_data("bbox")
    assert pdf_tlui.current_page == system // SYSTEMS_PER_PAGE + 1


def test_drawing_creates_marker_at_playhead(pdf_tlui):
    commands.execute("media.seek", 85)

    with undoable():
        drag(pdf_tlui.pdf_view, 1, (0.2, 0.1), (0.5, 0.2))

    assert len(pdf_tlui) == 9
    new = next(m for m in pdf_tlui if m.get_data("time") == 85)
    assert new.get_data("page_number") == 1
    assert new.get_data("bbox") == pytest.approx([0.2, 0.1, 0.3, 0.1], abs=0.01)


def test_drawing_updates_selected_marker(pdf_tlui):
    commands.execute("media.seek", 85)
    pdf_tlui.select_element(pdf_tlui[2])

    with undoable():
        drag(pdf_tlui.pdf_view, 1, (0.1, 0.5), (0.5, 0.6))

    assert len(pdf_tlui) == 8
    assert pdf_tlui[2].get_data("bbox") == pytest.approx([0.1, 0.5, 0.4, 0.1], abs=0.01)


def test_click_without_drag_changes_nothing(pdf_tlui):
    before = [m.get_data("bbox") for m in pdf_tlui]

    drag(pdf_tlui.pdf_view, 1, (0.5, 0.5), (0.501, 0.501))

    assert [m.get_data("bbox") for m in pdf_tlui] == before


def test_clear_region_from_context_menu(pdf_tlui):
    pdf_tlui.select_element(pdf_tlui[0])
    menu = pdf_tlui[0].CONTEXT_MENU_CLASS(pdf_tlui[0])

    with undoable():
        get_command_action(menu, "timeline.pdf.clear_region").trigger()

    assert pdf_tlui[0].get_data("bbox") is None
    assert len(pdf_tlui.pdf_view.regions) == 7


def test_regions_survive_save_and_reopen(pdf_tlui, tluis, tmp_path):
    before = [m.get_data("bbox") for m in pdf_tlui]

    save_and_reopen(tmp_path)

    reopened = next(t for t in tluis if isinstance(t.timeline, PdfTimeline))
    assert [m.get_data("bbox") for m in reopened] == before


def test_file_without_regions_still_loads(tluis, tmp_path):
    # A .tla from before this feature has no "bbox" key at all. Strip it from
    # the fixture to get one: the current version can't save that format.
    data = json.loads(FIXTURE.read_text())
    for timeline in data["timelines"].values():
        for component in timeline.get("components", {}).values():
            component.pop("bbox", None)
    old_file = tmp_path / "old.tla"
    old_file.write_text(json.dumps(data))

    commands.execute("file.open", str(old_file))

    tlui = next(t for t in tluis if isinstance(t.timeline, PdfTimeline))
    assert len(tlui) == 8
    assert all(m.get_data("bbox") is None for m in tlui)
    assert tlui.pdf_view.regions == []
