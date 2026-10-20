"""Builds repro/demo/maple-leaf-rag.tla: score following on a real piece.

Scott Joplin, Maple Leaf Rag (1899, public domain). The encoding is
source/Joplin_Maple_leaf_Rag.mei from music-encoding/sample-encodings
(ECL-2.0). pipeline/ turned it into the files next to this script:

- maple-leaf-rag.pdf        engraved by Verovio, 3 A4 pages
- maple-leaf-rag-zones.mei  Cartographer-style measure zones for that PDF
- maple-leaf-rag.mp3        3:11 piano performance with all repeats played,
                            rendered from the score (see PDF-REGION-REPRO.md)
- performance.json          that performance, measure by measure

This script assembles them through user commands, then saves with
`file.save_as`:

- media: maple-leaf-rag.mp3
- "Measures": beat timeline, one beat per quarter, at the performance's
  times. The pickup is a 1-beat measure, and measure numbers are reset at
  every repeat jump, so they read 1, 2…17, 2…16, 18, 19… as performed.
- "Score": PDF timeline on maple-leaf-rag.pdf, filled by
  `timelines.import.pdf_mei` from maple-leaf-rag-zones.mei, which gives one
  marker per performed measure (145) with the measure's region.
- "Form": hierarchy timeline, A A B B A C C D D, with Part I / Trio above.

Run from the repo root:

    uv run --python 3.12 python -m pytest -p tests.conftest -p no:xdist repro/demo/build_maple_leaf_demo.py -q

The .tla stores absolute paths to the PDF and the MP3, so rebuild after moving
the folder.
"""

import json
import subprocess
from pathlib import Path

from tests.mock import Serve
from tilia.requests import Get
from tilia.timelines.beat.timeline import BeatTimeline
from tilia.timelines.hierarchy.timeline import HierarchyTimeline
from tilia.timelines.pdf.timeline import PdfTimeline
from tilia.ui import commands

HERE = Path(__file__).resolve().parent
MEDIA = HERE / "maple-leaf-rag.mp3"
PDF = HERE / "maple-leaf-rag.pdf"
ZONES = HERE / "maple-leaf-rag-zones.mei"
OUT = HERE / "maple-leaf-rag.tla"

PERFORMANCE = json.loads((HERE / "performance.json").read_text())
SCORE = json.loads((HERE / "score.json").read_text())
QUARTERS = {m["index"]: m["length"] for m in SCORE["measures"]}

# (label, first performed position, last performed position, level)
FORM = [
    ("A", 0, 16, 1),
    ("A", 17, 32, 1),
    ("B", 33, 48, 1),
    ("B", 49, 64, 1),
    ("A", 65, 80, 1),
    ("C", 81, 96, 1),
    ("C", 97, 112, 1),
    ("D", 113, 128, 1),
    ("D", 129, 144, 1),
    ("Part I", 0, 80, 2),
    ("Trio", 81, 144, 2),
]


def media_duration() -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(MEDIA),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return round(float(result.stdout), 3)


def beats_of(measure: dict) -> list[float]:
    """Beat times of one performed measure: one per quarter, the pickup gets one."""
    count = max(1, round(QUARTERS[measure["index"]]))
    step = measure["length"] / max(QUARTERS[measure["index"]], 0.5)
    return [round(measure["start"] + k * step, 4) for k in range(count)]


def add_timeline(kind: str, name: str, **serves):
    with Serve(Get.FROM_USER_STRING, (True, name)):
        if kind == "beat":
            with Serve(Get.FROM_USER_BEAT_PATTERN, (True, [2])):
                commands.execute("timelines.add.beat")
        elif kind == "pdf":
            with Serve(Get.FROM_USER_PDF_PATH, (True, str(PDF))):
                commands.execute("timelines.add.pdf")
        else:
            commands.execute(f"timelines.add.{kind}")


def timeline_ui(tluis, cls):
    return next(t for t in tluis if isinstance(t.timeline, cls))


def test_build(tluis, tilia_state):
    tilia_state.media_path = str(MEDIA)
    tilia_state.duration = media_duration()

    # Beat timeline: beats at the performed times.
    add_timeline("beat", "Measures")
    beat_tlui = timeline_ui(tluis, BeatTimeline)
    performed = PERFORMANCE["measures"]
    first_beat_of = []
    for measure in performed:
        first_beat_of.append(len(beat_tlui))
        for time in beats_of(measure):
            commands.execute("timeline.beat.add", time=time)

    # The pickup is half a quarter: a 1-beat measure.
    beat_tlui.select_element(beat_tlui[0])
    commands.execute("timeline.beat.set_amount_in_measure", amount=1)
    beat_tlui.deselect_element(beat_tlui[0])

    # Number measures as performed: reset the number after every repeat jump.
    for position in range(1, len(performed)):
        number = performed[position]["index"]
        if number == performed[position - 1]["index"] + 1:
            continue
        beat = beat_tlui[first_beat_of[position]]
        beat_tlui.select_element(beat)
        with Serve(Get.FROM_USER_INT, (True, number)):
            commands.execute("timeline.beat.set_measure_number")
        beat_tlui.deselect_element(beat)

    # PDF timeline, filled from the measure zones.
    add_timeline("pdf", "Score")
    with Serve(Get.FROM_USER_YES_OR_NO, True):  # replace the default marker
        commands.execute("timelines.import.pdf_mei", path=str(ZONES))

    # Form.
    add_timeline("hierarchy", "Form")
    hierarchy_tl = timeline_ui(tluis, HierarchyTimeline).timeline
    hierarchy_tl.clear()  # drop the automatic whole-piece hierarchy
    for label, first, last, level in FORM:
        end = performed[last]["start"] + performed[last]["length"]
        commands.execute(
            "timeline.hierarchy.add",
            start=performed[first]["start"],
            end=round(end, 4),
            level=level,
            label=label,
        )

    commands.execute("file.save_as", str(OUT))

    beat_tl = beat_tlui.timeline
    assert beat_tl.measure_numbers == [m["index"] for m in performed]
    pdf_tl = timeline_ui(tluis, PdfTimeline).timeline
    assert len(pdf_tl) == len(performed) == 145
    assert [m.get_data("time") for m in pdf_tl] == [
        beat_tl.get_time_by_measure(1)[0]
    ] + [round(m["start"], 4) for m in performed[1:]]
    assert {m.get_data("page_number") for m in pdf_tl} == {1, 2, 3}
    assert len(hierarchy_tl) == len(FORM)
    assert OUT.exists()
