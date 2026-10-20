"""Headless checks for the Maple Leaf Rag demo (scenario S0c).

Opens repro/demo/maple-leaf-rag.tla (built by build_maple_leaf_demo.py) and
plays it through, measure by measure. Run from the repo root:

    uv run --python 3.12 python -m pytest -p tests.conftest -p no:xdist repro/demo/test_maple_leaf_demo.py -v
"""

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QRectF

from tilia.timelines.beat.timeline import BeatTimeline
from tilia.timelines.pdf.timeline import PdfTimeline
from tilia.ui import commands

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "maple-leaf-rag.tla"
PERFORMED = json.loads((HERE / "performance.json").read_text())["measures"]


@pytest.fixture
def demo(tluis):
    assert FIXTURE.exists(), "run repro/demo/build_maple_leaf_demo.py first"
    assert (
        "timelines.import.pdf_mei" in commands._name_to_callback
    ), "MEI import command not registered (are you on dev?)"
    commands.execute("file.open", str(FIXTURE))
    return tluis


def of(tluis, cls):
    return next(t for t in tluis if isinstance(t.timeline, cls))


def test_files_are_there():
    data = json.loads(FIXTURE.read_text())
    assert Path(data["media_path"]).exists()
    pdf = next(t for t in data["timelines"].values() if t["kind"] == "Pdf")
    assert Path(pdf["path"]).exists()


def test_measures_are_numbered_as_performed(demo):
    beat_tl = of(demo, BeatTimeline).timeline
    assert beat_tl.measure_numbers == [m["index"] for m in PERFORMED]


def test_one_marker_per_performed_measure(demo):
    pdf_tlui = of(demo, PdfTimeline)
    assert len(pdf_tlui) == 145
    assert {m.get_data("page_number") for m in pdf_tlui} == {1, 2, 3}


def test_repeat_jumps_back_to_the_same_box(demo):
    pdf_tlui = of(demo, PdfTimeline)
    # Measure 2 starts both passes of A (performed positions 1 and 17).
    first, second = pdf_tlui[1], pdf_tlui[17]
    assert first.get_data("bbox") == second.get_data("bbox")
    assert second.get_data("time") > first.get_data("time")


def test_current_measure_is_always_on_screen(demo):
    pdf_tlui = of(demo, PdfTimeline)
    viewer = pdf_tlui.pdf_view
    viewer.resize(820, 480)
    off_screen = []
    for position, measure in enumerate(PERFORMED):
        commands.execute("media.seek", measure["start"] + 0.05)
        (active,) = [r for r in viewer.regions if r.is_active]
        rect = viewer.region_rect(active)
        if not QRectF(viewer.viewport().rect()).contains(rect):
            off_screen.append((position, measure["index"]))
        assert active.bbox == pdf_tlui[position].get_data("bbox")
    assert off_screen == []
