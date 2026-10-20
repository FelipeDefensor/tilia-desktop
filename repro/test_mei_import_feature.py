"""Headless acceptance checks for importing measure regions from MEI (scenario S0b).

Two inputs:

- repro/score-zones.mei with repro/pdf-mei.tla (built by
  repro/build_pdf_region_fixture.py): 32 measures on the 2-page stand-in score.
- repro/cartographer-sample.mei: the test file shipped with the Cartographer App
  (public/testfile.xml, MIT licence), unchanged. 120 surfaces, zones only on
  surfaces 5 (22 measures) and 6 (44 measures), 66 measures in one movement.
  Imported against tests/resources/example.pdf, which has 5 pages, so it also
  covers zones beyond the end of the PDF.

Run from the repo root:

    uv run --python 3.12 python -m pytest -p tests.conftest -p no:xdist repro/test_mei_import_feature.py -v

On feat/pdf-marker-bbox everything passes. On dev every test errors with
"MEI import command not registered".
"""

from pathlib import Path

import pytest

from tests.mock import Serve
from tilia.requests import Get
from tilia.timelines.beat.timeline import BeatTimeline
from tilia.timelines.pdf.timeline import PdfTimeline
from tilia.ui import commands

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "pdf-mei.tla"
SCORE_MEI = HERE / "score-zones.mei"
CARTOGRAPHER_MEI = HERE / "cartographer-sample.mei"
EXAMPLE_PDF = HERE.parent / "tests" / "resources" / "example.pdf"

SECONDS_PER_MEASURE = 2.5


@pytest.fixture(autouse=True)
def require_feature(tluis):
    assert FIXTURE.exists(), "run repro/build_pdf_region_fixture.py first"
    assert (
        "timelines.import.pdf_mei" in commands._name_to_callback
    ), "MEI import command not registered (are you on dev?)"


def pdf_tlui_of(tluis):
    return next(t for t in tluis if isinstance(t.timeline, PdfTimeline))


@pytest.fixture
def imported(tluis):
    commands.execute("file.open", str(FIXTURE))
    with Serve(Get.FROM_USER_YES_OR_NO, True):  # replace the whole-page marker
        commands.execute("timelines.import.pdf_mei", path=str(SCORE_MEI))
    return pdf_tlui_of(tluis)


def test_one_marker_per_measure(imported):
    assert len(imported) == 32
    assert [m.get_data("time") for m in imported] == [
        n * SECONDS_PER_MEASURE for n in range(32)
    ]


def test_measures_land_on_their_pages(imported):
    pages = [m.get_data("page_number") for m in imported]
    assert pages == [1] * 16 + [2] * 16


def test_regions_frame_measures(imported):
    # Measure 1: first quarter of the first system, padded staff height.
    assert imported[0].get_data("bbox") == pytest.approx(
        [0.1, 0.09, 0.2, 0.12], abs=0.001
    )
    # Measure 6: second measure of the second system.
    assert imported[5].get_data("bbox") == pytest.approx(
        [0.3, 0.3, 0.2, 0.12], abs=0.001
    )


@pytest.mark.parametrize("measure", [1, 6, 17, 32])
def test_playback_highlights_current_measure(imported, measure):
    commands.execute("media.seek", (measure - 1) * SECONDS_PER_MEASURE + 1)

    (active,) = [r for r in imported.pdf_view.regions if r.is_active]
    assert active.bbox == imported[measure - 1].get_data("bbox")
    assert imported.current_page == (1 if measure <= 16 else 2)


def test_import_is_undoable(tluis):
    commands.execute("file.open", str(FIXTURE))
    with Serve(Get.FROM_USER_YES_OR_NO, True):
        commands.execute("timelines.import.pdf_mei", path=str(SCORE_MEI))

    commands.execute("edit.undo")
    pdf_tlui = pdf_tlui_of(tluis)
    assert [(m.get_data("time"), m.get_data("bbox")) for m in pdf_tlui] == [(0, None)]

    commands.execute("edit.redo")
    assert len(pdf_tlui_of(tluis)) == 32


def test_cartographer_sample(tluis, tilia_errors):
    with (
        Serve(Get.FROM_USER_STRING, (True, "Beethoven")),
        Serve(Get.FROM_USER_PDF_PATH, (True, str(EXAMPLE_PDF))),
    ):
        commands.execute("timelines.add.pdf")
    with (
        Serve(Get.FROM_USER_STRING, (True, "Measures")),
        Serve(Get.FROM_USER_BEAT_PATTERN, (True, [1])),
    ):
        commands.execute("timelines.add.beat")
    for i in range(66):
        commands.execute("timeline.beat.add", time=i)
    assert (
        next(
            t for t in tluis if isinstance(t.timeline, BeatTimeline)
        ).timeline.measure_count
        == 66
    )

    with Serve(Get.FROM_USER_YES_OR_NO, True):
        commands.execute("timelines.import.pdf_mei", path=str(CARTOGRAPHER_MEI))

    pdf_tlui = pdf_tlui_of(tluis)
    # Surface 5 (22 measures) fits in the 5-page PDF; surface 6 doesn't.
    assert len(pdf_tlui) == 22
    assert {m.get_data("page_number") for m in pdf_tlui} == {5}
    assert [m.get_data("time") for m in pdf_tlui] == list(range(22))
    assert all(m.get_data("bbox") for m in pdf_tlui)
    tilia_errors.assert_in_error_message("on page 6, but the PDF has 5 pages")
