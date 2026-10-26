"""Builds repro/schema.tla: a galant phrase annotated with three schemata.

repro/galant-phrase.musicxml is a six-measure, two-voice phrase in C major
made of a Romanesca (stepwise), a Prinner and a Do-Re-Mi, one stage per half
note. This script imports it through user commands, with OSMD drawing the
score (it loads from cdn.jsdelivr.net, so this needs a connection), places
every degree of the three schemata on its notehead with
`timeline.score.add_schema_degree` (the command a drop runs), and saves with
`file.save_as`.

Run from the repo root:

    uv run --python 3.12 python -m pytest -p tests.conftest -p no:xdist repro/build_schema_fixture.py -q

The .tla has no media: the timelines run over a 14.4 s phrase (♩ = 100).
"""

import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from tests.mock import Serve, patch_file_dialog, patch_yes_or_no_dialog
from tilia.requests import Get
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.score.timeline import ScoreTimeline
from tilia.ui import commands

HERE = Path(__file__).resolve().parent
SCORE = HERE / "galant-phrase.musicxml"
OUT = HERE / "schema.tla"

BEAT = 0.6  # seconds
BEATS = 24  # six measures of 4/4

# (schema, first column): column k is the k-th half note of the phrase.
SCHEMATA = [("Romanesca (stepwise)", 0), ("Prinner", 4), ("Do-Re-Mi", 8)]
STAGE_COUNTS = {"Romanesca (stepwise)": 4, "Prinner": 4, "Do-Re-Mi": 3}


def wait_until(condition, timeout: float = 60) -> bool:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.02)
    return bool(condition())


def noteheads_by_staff(viewer) -> tuple[list[str], list[str]]:
    """The treble and the bass noteheads, each left to right."""
    ys = [rect.center().y() for rect, _ in viewer.noteheads.values()]
    middle = (min(ys) + max(ys)) / 2
    upper, lower = [], []
    for notehead, (rect, _) in viewer.noteheads.items():
        (upper if rect.center().y() < middle else lower).append(notehead)

    def by_x(noteheads):
        return sorted(noteheads, key=lambda n: viewer.noteheads[n][0].x())

    return by_x(upper), by_x(lower)


def score_timeline_ui(tluis):
    return next(t for t in tluis if isinstance(t.timeline, ScoreTimeline))


def test_build(tluis, tilia_state):
    tilia_state.duration = BEAT * BEATS

    with (
        Serve(Get.FROM_USER_STRING, (True, "Measures")),
        Serve(Get.FROM_USER_BEAT_PATTERN, (True, [4])),
    ):
        commands.execute("timelines.add.beat")
    for k in range(BEATS):
        commands.execute("timeline.beat.add", time=round(k * BEAT, 4))

    with Serve(Get.FROM_USER_STRING, (True, "Score")):
        commands.execute("timelines.add.score")
    with patch_file_dialog(True, [str(SCORE)]), patch_yes_or_no_dialog(False):
        commands.execute("timelines.import.score")

    score_tlui = score_timeline_ui(tluis)
    assert wait_until(
        lambda: score_tlui.svg_view is not None and score_tlui.svg_view.is_svg_loaded
    ), "OSMD didn't draw the score (no connection?)"
    viewer = score_tlui.svg_view

    upper, lower = noteheads_by_staff(viewer)
    assert len(upper) == len(lower) == 11, (len(upper), len(lower))

    for schema, first in SCHEMATA:
        for stage in range(STAGE_COUNTS[schema]):
            for voice, noteheads in (("upper", upper), ("lower", lower)):
                assert commands.execute(
                    "timeline.score.add_schema_degree",
                    notehead=noteheads[first + stage],
                    schema=schema,
                    stage=stage,
                    voice=voice,
                    index=0,
                )
        commands.execute("timeline.score.finish_schema_instance")

    commands.execute("file.save_as", str(OUT))

    instances = score_tlui.timeline.get_components_by_attr(
        "KIND", ComponentKind.SCHEMA_INSTANCE
    )
    assert sorted(i.schema["name"] for i in instances) == sorted(STAGE_COUNTS)
    assert sum(len(i.degrees) for i in instances) == 2 * sum(STAGE_COUNTS.values())
    assert OUT.exists()
