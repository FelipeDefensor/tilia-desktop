"""Headless acceptance checks for the schema builder (scenario S0).

Opens repro/schema.tla (built by repro/build_schema_fixture.py) and goes
through the same commands and viewer events the GUI uses. Run from the repo
root:

    uv run --python 3.12 python -m pytest -p tests.conftest -p no:xdist repro/test_schema_feature.py -v

On feat/schema-builder everything passes. On dev every test errors with
"no schema instance component", which shows the feature isn't there.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from tests.utils import save_and_reopen, undoable
from tilia.requests import Get, get
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.score.timeline import ScoreTimeline
from tilia.ui import commands

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "schema.tla"

# Mirrors build_schema_fixture.SCHEMATA: the half-note columns each covers.
EXPECTED = {
    "Romanesca (stepwise)": ([1, 5, 1, 1], [1, 7, 6, 3], range(0, 4)),
    "Prinner": ([6, 5, 4, 3], [4, 3, 2, 1], range(4, 8)),
    "Do-Re-Mi": ([1, 2, 3], [1, 7, 1], range(8, 11)),
}


@pytest.fixture(autouse=True)
def require_feature(tluis):
    assert FIXTURE.exists(), "run repro/build_schema_fixture.py first"
    # Checked before opening: dev can't read the file's schema instances.
    assert hasattr(
        ComponentKind, "SCHEMA_INSTANCE"
    ), "no schema instance component (are you on dev?)"
    # The score viewer registers its commands, so open the file first.
    commands.execute("file.open", str(FIXTURE))
    assert (
        "timeline.score.add_schema_degree" in commands._name_to_callback
    ), "schema commands not registered (are you on dev?)"


def viewer():
    return get(Get.TIMELINE_UI_BY_ATTR, "timeline_class", ScoreTimeline).svg_view


def instances():
    timeline = get(Get.TIMELINE_UI_BY_ATTR, "timeline_class", ScoreTimeline).timeline
    return {
        i.schema["name"]: i
        for i in timeline.get_components_by_attr("KIND", ComponentKind.SCHEMA_INSTANCE)
    }


def columns(v):
    """Notehead id -> (staff, half-note column), staff 0 being the treble."""
    ys = [r.center().y() for r, _ in v.noteheads.values()]
    middle = (min(ys) + max(ys)) / 2
    result = {}
    for staff in (0, 1):
        heads = sorted(
            (
                n
                for n, (r, _) in v.noteheads.items()
                if (r.center().y() < middle) == (staff == 0)
            ),
            key=lambda n: v.noteheads[n][0].x(),
        )
        for column, n in enumerate(heads):
            result[n] = (staff, column)
    return result


def drop(v, notehead, schema, stage, voice):
    from tilia.timelines.score.schema import stage_degree
    from tilia.ui.schema import library
    from tilia.ui.schema.diagram import degree_mime_data

    degree = stage_degree(library.get_schema(schema), stage, voice, 0)
    mime = degree_mime_data(schema, stage, voice, 0, degree)
    pos = v.view.mapFromScene(v.noteheads[notehead][0].center())
    args = (
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    viewport = v.view.viewport()
    QApplication.sendEvent(viewport, QDragEnterEvent(pos, *args))
    QApplication.sendEvent(viewport, QDragMoveEvent(pos, *args))
    QApplication.sendEvent(viewport, QDropEvent(QPointF(pos), *args))


def test_three_instances_are_loaded():
    assert sorted(instances()) == sorted(EXPECTED)


@pytest.mark.parametrize("name", EXPECTED)
def test_degrees_sit_on_their_notes(name):
    upper, lower, cols = EXPECTED[name]
    where = columns(viewer())
    placed = instances()[name].degrees
    for voice, staff, values in (("upper", 0, upper), ("lower", 1, lower)):
        in_voice = sorted(
            (d for d in placed if d["voice"] == voice), key=lambda d: d["stage"]
        )
        assert [d["value"] for d in in_voice] == values
        assert [where[d["notehead"]] for d in in_voice] == [(staff, c) for c in cols]


def test_every_degree_is_drawn():
    v = viewer()
    drawn = sum(len(d.degrees) for d in v.schema_instances.values())
    assert drawn == sum(len(i.degrees) for i in instances().values()) == 22
    assert all(len(d.lines) == 2 for d in v.schema_instances.values())


def test_circles_leave_the_notes_free():
    v = viewer()
    for drawn in v.schema_instances.values():
        for item in [*drawn.degrees, *drawn.lines]:
            assert not item.sceneBoundingRect().intersects(v.system_rect)
        for halo, degree in zip(drawn.halos, drawn.degrees, strict=True):
            assert halo.rect().contains(v.noteheads[degree.notehead][0])


def test_lane_shows_instances_as_bars():
    score = get(Get.TIMELINE_UI_BY_ATTR, "timeline_class", ScoreTimeline)
    bars = {
        e.get_data("schema")["name"]: e
        for e in score.element_manager.get_elements_by_attribute(
            "kind", ComponentKind.SCHEMA_INSTANCE
        )
    }
    # Two measures of 4/4 at 0.6 s a beat each; the last stage of Do-Re-Mi is
    # the final whole note, which the importer ends at 13.05 s.
    assert bars["Romanesca (stepwise)"].spans == [(0.0, 4.8)]
    assert bars["Prinner"].spans == [(4.8, 9.6)]
    (start, end), = bars["Do-Re-Mi"].spans
    assert start == 9.6 and end == pytest.approx(13.05)
    # They follow each other, so they share one row under the staves.
    assert {e.row for e in bars.values()} == {0}
    assert score.get_height() == score.get_staves_height() + (
        score.get_schema_lane_height()
    )


def test_palette_opens_from_toolbar():
    v = viewer()
    get(Get.MAIN_WINDOW).show()
    v.show()
    assert not v.schema_palette.isVisible()
    commands.execute("timeline.score.toggle_schemata")
    assert v.schema_palette.isVisible()


def test_drop_starts_a_new_instance():
    v = viewer()
    notehead = next(n for n, (s, c) in columns(v).items() if (s, c) == (0, 10))
    with undoable():
        drop(v, notehead, "Meyer", 3, "upper")
        assert len(instances()) == 4
        assert instances()["Meyer"].degrees[0]["notehead"] == notehead


def test_clicking_a_degree_continues_its_instance():
    v = viewer()
    prinner = instances()["Prinner"]
    degree = next(d for d in v.schema_instances[prinner.id].degrees)
    QTest.mouseClick(
        v.view.viewport(),
        Qt.MouseButton.LeftButton,
        pos=v.view.mapFromScene(degree.scenePos()),
    )
    assert v.active_schema_instance == prinner.id
    assert "8 of 8" in v.schema_palette.instance_label.text()


def test_shift_click_removes_a_degree():
    v = viewer()
    prinner = instances()["Prinner"]
    degree = v.schema_instances[prinner.id].degrees[0]
    with undoable():
        QTest.mouseClick(
            v.view.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
            v.view.mapFromScene(degree.scenePos()),
        )
        assert len(instances()["Prinner"].degrees) == 7


def test_new_schema_from_editor(monkeypatch):
    from tilia.ui.schema import library
    from tilia.ui.schema.editor import SchemaEditor

    def fill(dialog):
        dialog.name.setText("Lully cadence")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SchemaEditor, "exec", fill)
    viewer().schema_palette.new_button.click()
    assert library.is_custom("Lully cadence")
    assert viewer().schema_palette.schema["name"] == "Lully cadence"


def test_round_trip(tmp_path):
    before = {n: (i.schema, i.degrees) for n, i in instances().items()}
    save_and_reopen(tmp_path)
    assert {n: (i.schema, i.degrees) for n, i in instances().items()} == before
    assert sum(len(d.degrees) for d in viewer().schema_instances.values()) == 22
