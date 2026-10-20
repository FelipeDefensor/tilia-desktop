"""Builds repro/score.pdf, repro/pdf-region.tla, repro/score-zones.mei and
repro/pdf-mei.tla for the PDF region prototype and its MEI import.

score.pdf is a stand-in for a scanned score: 2 A4 pages, 4 systems each, every
system a 5-line staff with 4 measures and a "System N" label. It is drawn here
with QPdfWriter so the repro doesn't depend on a copyrighted score.

pdf-region.tla has one PDF timeline on score.pdf with 8 markers, one per
system, every 10 s from 0 s to 70 s. Each marker's region is that system's
bounding box. The file is built by driving the real app headless through user
commands (`timeline.pdf.set_region`) and saved with `file.save_as`, so the JSON
is never hand-written. Media-free: 100 s media length, no media file.

score-zones.mei is what the Cartographer App would export for score.pdf scanned
at A4/300 dpi (2480 × 3508 px): one <surface> per page and one measure <zone>
per measure, 32 measures numbered 1–32. It's written by hand on purpose: it
stands for a file from another program.

pdf-mei.tla is the starting point for importing it: a PDF timeline on
score.pdf (just the default whole-page marker) and a 4/4 beat timeline with 32
measures, 2.5 s each (measure n starts at (n - 1) * 2.5 s).

Run from the repo root (`python -m` puts the root on sys.path for
`-p tests.conftest`):

    uv run --python 3.12 python -m pytest -p tests.conftest -p no:xdist repro/build_pdf_region_fixture.py -q

The .tla stores score.pdf's absolute path, so rebuild after moving the folder.
"""

from pathlib import Path

from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
)

from tests.mock import Serve
from tilia.requests import Get
from tilia.timelines.beat.timeline import BeatTimeline
from tilia.timelines.pdf.timeline import PdfTimeline
from tilia.ui import commands

HERE = Path(__file__).resolve().parent
PDF = HERE / "score.pdf"
OUT = HERE / "pdf-region.tla"
MEI = HERE / "score-zones.mei"
MEI_OUT = HERE / "pdf-mei.tla"

IMAGE_WIDTH, IMAGE_HEIGHT = 2480, 3508  # A4 at 300 dpi
SECONDS_PER_MEASURE = 2.5
BEATS_PER_MEASURE = 4

PAGES = 2
SYSTEMS_PER_PAGE = 4
MEASURES_PER_SYSTEM = 4
SECONDS_PER_SYSTEM = 10

# System layout, relative to the page. Each system's region is its staff plus
# a little padding, so the boxes visibly frame the staves.
LEFT, RIGHT = 0.1, 0.9
FIRST_STAFF_TOP = 0.12
SYSTEM_STEP = 0.21
STAFF_HEIGHT = 0.06
PADDING = 0.03


def system_bbox(index_on_page: int) -> list[float]:
    top = FIRST_STAFF_TOP + index_on_page * SYSTEM_STEP
    return [
        round(LEFT - PADDING, 4),
        round(top - PADDING, 4),
        round(RIGHT - LEFT + 2 * PADDING, 4),
        round(STAFF_HEIGHT + 2 * PADDING, 4),
    ]


def expected_markers() -> list[tuple[float, int, list[float]]]:
    """(time, page_number, bbox) for every system, in playback order."""
    return [
        (
            (page * SYSTEMS_PER_PAGE + i) * SECONDS_PER_SYSTEM,
            page + 1,
            system_bbox(i),
        )
        for page in range(PAGES)
        for i in range(SYSTEMS_PER_PAGE)
    ]


def write_score_pdf(path: Path) -> None:
    writer = QPdfWriter(str(path))
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(0, 0, 0, 0),
        )
    )
    writer.setResolution(72)
    painter = QPainter(writer)
    width, height = writer.width(), writer.height()

    for page in range(PAGES):
        if page:
            writer.newPage()
        painter.setFont(QFont("Helvetica", 14))
        painter.drawText(
            QRectF(0, 0.03 * height, width, 0.05 * height),
            Qt.AlignmentFlag.AlignCenter,
            f"Prototype score — page {page + 1}",
        )
        for i in range(SYSTEMS_PER_PAGE):
            number = page * SYSTEMS_PER_PAGE + i + 1
            top = (FIRST_STAFF_TOP + i * SYSTEM_STEP) * height
            left, right = LEFT * width, RIGHT * width
            line_gap = STAFF_HEIGHT * height / 4

            painter.setPen(QPen(QColor("black"), 1))
            for line in range(5):
                y = top + line * line_gap
                painter.drawLine(QPointF(left, y), QPointF(right, y))
            for bar in range(MEASURES_PER_SYSTEM + 1):
                x = left + bar * (right - left) / MEASURES_PER_SYSTEM
                painter.drawLine(QPointF(x, top), QPointF(x, top + 4 * line_gap))

            painter.setFont(QFont("Helvetica", 9))
            painter.drawText(QPointF(left, top - 6), f"System {number}")

    painter.end()


def test_build(tluis):
    write_score_pdf(PDF)

    with (
        Serve(Get.FROM_USER_STRING, (True, "Score")),
        Serve(Get.FROM_USER_PDF_PATH, (True, str(PDF))),
    ):
        commands.execute("timelines.add.pdf")

    pdf_tlui = next(t for t in tluis if isinstance(t.timeline, PdfTimeline))
    assert pdf_tlui.timeline.get_data("page_total") == PAGES

    # The new timeline already has a whole-page marker at 0 s;
    # set_region updates it in place, then creates the rest.
    for time, page_number, bbox in expected_markers():
        commands.execute(
            "timeline.pdf.set_region",
            timeline_id=pdf_tlui.id,
            page_number=page_number,
            bbox=bbox,
            time=time,
        )

    commands.execute("file.save_as", str(OUT))

    assert [
        (m.get_data("time"), m.get_data("page_number"), m.get_data("bbox"))
        for m in pdf_tlui.timeline
    ] == expected_markers()
    assert OUT.exists()


def measure_zone(index_on_page: int, measure_in_system: int) -> tuple[int, ...]:
    """(ulx, uly, lrx, lry) in image pixels, framing the staff vertically."""
    top = FIRST_STAFF_TOP + index_on_page * SYSTEM_STEP
    width = (RIGHT - LEFT) / MEASURES_PER_SYSTEM
    left = LEFT + measure_in_system * width
    return (
        round(left * IMAGE_WIDTH),
        round((top - PADDING) * IMAGE_HEIGHT),
        round((left + width) * IMAGE_WIDTH),
        round((top + STAFF_HEIGHT + PADDING) * IMAGE_HEIGHT),
    )


def expected_mei_markers() -> list[tuple[float, int, list[float]]]:
    """(time, page_number, bbox) for every measure, after importing score-zones.mei."""
    markers = []
    number = 0
    for page in range(PAGES):
        for system in range(SYSTEMS_PER_PAGE):
            for measure in range(MEASURES_PER_SYSTEM):
                ulx, uly, lrx, lry = measure_zone(system, measure)
                markers.append(
                    (
                        number * SECONDS_PER_MEASURE,
                        page + 1,
                        [
                            ulx / IMAGE_WIDTH,
                            uly / IMAGE_HEIGHT,
                            (lrx - ulx) / IMAGE_WIDTH,
                            (lry - uly) / IMAGE_HEIGHT,
                        ],
                    )
                )
                number += 1
    return markers


def write_score_mei(path: Path) -> None:
    surfaces = []
    body = []
    number = 0
    for page in range(PAGES):
        zones = []
        body.append(f'<pb n="{page + 1}" facs="#s{page + 1}"/>')
        for system in range(SYSTEMS_PER_PAGE):
            for measure in range(MEASURES_PER_SYSTEM):
                number += 1
                ulx, uly, lrx, lry = measure_zone(system, measure)
                zones.append(
                    f'        <zone xml:id="z{number}" type="measure" '
                    f'ulx="{ulx}" uly="{uly}" lrx="{lrx}" lry="{lry}"/>'
                )
                body.append(
                    f'<measure xml:id="m{number}" n="{number}" facs="#z{number}"/>'
                )
            body.append("<sb/>")
        surfaces.append(
            f'      <surface xml:id="s{page + 1}" n="{page + 1}" ulx="0" uly="0" '
            f'lrx="{IMAGE_WIDTH}" lry="{IMAGE_HEIGHT}">\n'
            f'        <graphic target="score-{page + 1}.jpg" type="facsimile" '
            f'width="{IMAGE_WIDTH}" height="{IMAGE_HEIGHT}"/>\n'
            + "\n".join(zones)
            + "\n      </surface>"
        )

    body_xml = "\n            ".join(body)
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.0.0-dev">
  <meiHead><fileDesc><titleStmt><title>Prototype score</title></titleStmt>
    <pubStmt/></fileDesc></meiHead>
  <music>
    <facsimile>
{chr(10).join(surfaces)}
    </facsimile>
    <body>
      <mdiv label="Movement 1" n="1">
        <score>
          <section>
            {body_xml}
          </section>
        </score>
      </mdiv>
    </body>
  </music>
</mei>
"""
    )


def test_build_mei_fixture(tluis):
    if not PDF.exists():
        write_score_pdf(PDF)
    write_score_mei(MEI)

    with (
        Serve(Get.FROM_USER_STRING, (True, "Score")),
        Serve(Get.FROM_USER_PDF_PATH, (True, str(PDF))),
    ):
        commands.execute("timelines.add.pdf")
    with (
        Serve(Get.FROM_USER_STRING, (True, "Measures")),
        Serve(Get.FROM_USER_BEAT_PATTERN, (True, [BEATS_PER_MEASURE])),
    ):
        commands.execute("timelines.add.beat")

    measure_count = PAGES * SYSTEMS_PER_PAGE * MEASURES_PER_SYSTEM
    beat_length = SECONDS_PER_MEASURE / BEATS_PER_MEASURE
    for i in range(measure_count * BEATS_PER_MEASURE):
        commands.execute("timeline.beat.add", time=i * beat_length)

    commands.execute("file.save_as", str(MEI_OUT))

    beat_tl = next(t for t in tluis if isinstance(t.timeline, BeatTimeline)).timeline
    assert beat_tl.measure_count == measure_count
    assert beat_tl.get_time_by_measure(measure_count) == [
        (measure_count - 1) * SECONDS_PER_MEASURE
    ]
    assert MEI_OUT.exists()
