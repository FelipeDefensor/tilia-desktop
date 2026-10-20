import json
from unittest.mock import patch

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.ui.timelines.interact import click_timeline_ui_view
from tests.utils import save_and_reopen, undoable
from tilia.requests import Get, Post, get, post
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.score.schema import stage_degree
from tilia.timelines.score.timeline import ScoreTimeline
from tilia.ui import commands
from tilia.ui.coords import time_x_converter
from tilia.ui.schema import library
from tilia.ui.schema.diagram import DEGREE_MIME_TYPE, degree_mime_data
from tilia.ui.schema.items import SvgSchemaDegree
from tilia.ui.windows.svg_viewer import SvgViewer

NOTE_XS = [10.0, 100.0, 200.0, 300.0]


def _make_score_svg():
    """Stave notes as OSMD draws them: the noteheads are groups without ids
    inside each stave note. The first stave note is a two-note chord."""
    notes = []
    for i, x in enumerate(NOTE_XS):
        ys = [40, 60] if i == 0 else [50]
        heads = "".join(
            f'<g class="vf-notehead"><rect x="{x}" y="{y}" width="8" height="6"/></g>'
            for y in ys
        )
        notes.append(f'<g class="vf-stavenote" id="note{i}">{heads}</g>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 120" '
        f'width="400" height="120"><g class="staffline">{"".join(notes)}</g></svg>'
    )


@pytest.fixture
def scored_beat_tl(beat_tl):
    beat_tl.beat_pattern = [1]
    for i in range(4):
        beat_tl.create_beat(i)
    beat_tl.measure_numbers = [0, 1, 2, 3]
    beat_tl.recalculate_measures()
    return beat_tl


@pytest.fixture
def svg_viewer(score_tlui, score_tl, scored_beat_tl):
    """See tests.ui.windows.test_svg_viewer.svg_viewer."""
    score_tl.set_data(
        "viewer_beat_x", dict(zip([0.0, 1.0, 2.0, 3.0], NOTE_XS, strict=True))
    )
    viewer = score_tlui.get_or_create_svg_view()
    viewer.load_svg_data(_make_score_svg())
    get(Get.MAIN_WINDOW).show()
    viewer.show()
    QApplication.processEvents()
    post(Post.APP_STATE_RECORD, "svg_viewer fixture")
    return viewer


def _viewer() -> SvgViewer:
    """The current viewer: opening a file builds a new one."""
    return get(Get.TIMELINE_UI_BY_ATTR, "timeline_class", ScoreTimeline).svg_view


def _instances():
    score_tl = get(Get.TIMELINE_UI_BY_ATTR, "timeline_class", ScoreTimeline).timeline
    return sorted(
        score_tl.get_components_by_attr("KIND", ComponentKind.SCHEMA_INSTANCE),
        key=lambda c: c.id,
    )


def _drawn_degrees(viewer: SvgViewer) -> list[SvgSchemaDegree]:
    return [i for i in viewer.scene.items() if isinstance(i, SvgSchemaDegree)]


def _viewport_pos(viewer: SvgViewer, notehead: str) -> QPoint:
    return viewer.view.mapFromScene(viewer.noteheads[notehead][0].center())


def _drop(viewer, mime, pos: QPoint) -> None:
    """Drags `mime` over the viewer to `pos` and drops it there."""
    viewport = viewer.view.viewport()
    action = Qt.DropAction.CopyAction
    buttons, modifiers = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    QApplication.sendEvent(
        viewport, QDragEnterEvent(pos, action, mime, buttons, modifiers)
    )
    QApplication.sendEvent(
        viewport, QDragMoveEvent(pos, action, mime, buttons, modifiers)
    )
    QApplication.sendEvent(
        viewport, QDropEvent(QPointF(pos), action, mime, buttons, modifiers)
    )


def drop_degree(viewer, notehead, schema="Prinner", stage=0, voice="upper", index=0):
    degree = stage_degree(library.get_schema(schema), stage, voice, index)
    mime = degree_mime_data(schema, stage, voice, index, degree)
    _drop(viewer, mime, _viewport_pos(viewer, notehead))


class TestNoteheads:
    def test_noteheads_get_ids(self, svg_viewer):
        assert sorted(svg_viewer.noteheads) == [
            "note0-notehead0",
            "note0-notehead1",
            "note1-notehead0",
            "note2-notehead0",
            "note3-notehead0",
        ]

    def test_ids_are_saved_with_the_score(self, svg_viewer, score_tl):
        assert 'id="note0-notehead1"' in score_tl.svg_data

    def test_ids_survive_reload(self, svg_viewer, tmp_path):
        before = sorted(svg_viewer.noteheads)
        save_and_reopen(tmp_path)
        assert sorted(_viewer().noteheads) == before

    def test_notehead_at_finds_the_closest_one(self, svg_viewer):
        rect = svg_viewer.noteheads["note1-notehead0"][0]
        assert svg_viewer.notehead_at(rect.center()) == "note1-notehead0"
        assert svg_viewer.notehead_at(rect.center() + QPointF(5, 0)) == (
            "note1-notehead0"
        )
        assert svg_viewer.notehead_at(QPointF(150, 110)) is None


class TestDropDegree:
    def test_drop_creates_instance(self, svg_viewer):
        with undoable():
            drop_degree(svg_viewer, "note1-notehead0")
            (instance,) = _instances()
            assert instance.schema["name"] == "Prinner"
            assert instance.degrees == [
                {
                    "notehead": "note1-notehead0",
                    "stage": 0,
                    "voice": "upper",
                    "index": 0,
                    "value": 6,
                    "accidental": "=",
                }
            ]
            assert len(_drawn_degrees(svg_viewer)) == 1

    def test_drop_beside_notehead_lands_on_it(self, svg_viewer):
        pos = _viewport_pos(svg_viewer, "note2-notehead0") + QPoint(4, 0)
        schema = library.get_schema("Prinner")
        mime = degree_mime_data(
            "Prinner", 1, "upper", 0, schema["stages"][1]["upper"][0]
        )
        _drop(svg_viewer, mime, pos)
        assert _instances()[0].degrees[0]["notehead"] == "note2-notehead0"

    def test_drop_far_from_noteheads_does_nothing(self, svg_viewer):
        schema = library.get_schema("Prinner")
        mime = degree_mime_data(
            "Prinner", 0, "upper", 0, schema["stages"][0]["upper"][0]
        )
        _drop(svg_viewer, mime, svg_viewer.view.mapFromScene(QPointF(150, 115)))
        assert _instances() == []

    def test_drop_other_data_is_ignored(self, svg_viewer):
        from PySide6.QtCore import QMimeData

        mime = QMimeData()
        mime.setText("6")
        _drop(svg_viewer, mime, _viewport_pos(svg_viewer, "note1-notehead0"))
        assert _instances() == []

    def test_next_drops_add_to_the_instance(self, svg_viewer):
        drop_degree(svg_viewer, "note0-notehead0", stage=0, voice="upper")
        drop_degree(svg_viewer, "note0-notehead1", stage=0, voice="lower")
        with undoable():
            drop_degree(svg_viewer, "note1-notehead0", stage=1, voice="upper")
            (instance,) = _instances()
            assert [(d["stage"], d["voice"]) for d in instance.degrees] == [
                (0, "upper"),
                (0, "lower"),
                (1, "upper"),
            ]

    def test_dropping_a_placed_degree_again_moves_it(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0")
        drop_degree(svg_viewer, "note2-notehead0")
        (instance,) = _instances()
        assert [d["notehead"] for d in instance.degrees] == ["note2-notehead0"]

    def test_other_schema_starts_new_instance(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0", schema="Prinner")
        drop_degree(svg_viewer, "note1-notehead0", schema="Do-Re-Mi")
        assert [i.schema["name"] for i in _instances()] == ["Prinner", "Do-Re-Mi"]
        # Both circles stand over the shared note, in rows of their own.
        a, b = _drawn_degrees(svg_viewer)
        assert a.x() == b.x()
        assert abs(a.y() - b.y()) >= 2 * a.radius

    def test_finish_starts_new_instance(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0")
        commands.execute("timeline.score.finish_schema_instance")
        drop_degree(svg_viewer, "note2-notehead0")
        assert len(_instances()) == 2

    def test_drop_highlights_target_while_dragging(self, svg_viewer):
        schema = library.get_schema("Prinner")
        mime = degree_mime_data(
            "Prinner", 0, "upper", 0, schema["stages"][0]["upper"][0]
        )
        pos = _viewport_pos(svg_viewer, "note1-notehead0")
        viewport = svg_viewer.view.viewport()
        args = (
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(viewport, QDragEnterEvent(pos, *args))
        QApplication.sendEvent(viewport, QDragMoveEvent(pos, *args))
        highlight = svg_viewer.drop_highlight
        assert highlight.isVisible()
        assert highlight.rect().contains(svg_viewer.noteheads["note1-notehead0"][0])

    def test_lines_join_the_degrees_of_a_voice(self, svg_viewer):
        for stage, notehead in enumerate(["note1-notehead0", "note2-notehead0"]):
            drop_degree(svg_viewer, notehead, stage=stage)
        drawn = svg_viewer.schema_instances[_instances()[0].id]
        assert len(drawn.lines) == 1
        assert drawn.label.text() == "Prinner"


class TestRemoveDegree:
    def test_shift_click_removes_degree(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0", stage=0)
        drop_degree(svg_viewer, "note2-notehead0", stage=1)
        degree = next(
            d for d in _drawn_degrees(svg_viewer) if d.notehead == "note1-notehead0"
        )
        pos = svg_viewer.view.mapFromScene(degree.scenePos())
        with undoable():
            QTest.mouseClick(
                svg_viewer.view.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.ShiftModifier,
                pos,
            )
            (instance,) = _instances()
            assert [d["notehead"] for d in instance.degrees] == ["note2-notehead0"]

    def test_removing_last_degree_deletes_instance(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0")
        instance = _instances()[0]
        with undoable():
            commands.execute(
                "timeline.score.remove_schema_degree",
                instance_id=instance.id,
                notehead="note1-notehead0",
            )
            assert _instances() == []
            assert _drawn_degrees(svg_viewer) == []

    def test_delete_key_removes_selected_degrees(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0", stage=0)
        drop_degree(svg_viewer, "note2-notehead0", stage=1)
        degree = next(
            d for d in _drawn_degrees(svg_viewer) if d.notehead == "note2-notehead0"
        )
        degree.setSelected(True)
        with undoable():
            QTest.keyClick(svg_viewer, Qt.Key.Key_Delete)
            assert [d["notehead"] for d in _instances()[0].degrees] == [
                "note1-notehead0"
            ]

    def test_delete_instance(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0", stage=0)
        drop_degree(svg_viewer, "note2-notehead0", stage=1)
        with undoable():
            commands.execute("timeline.score.delete_schema_instance")
            assert _instances() == []
            assert _drawn_degrees(svg_viewer) == []


class TestActiveInstance:
    def test_clicking_a_degree_activates_its_instance(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0", schema="Prinner")
        drop_degree(svg_viewer, "note2-notehead0", schema="Meyer")
        prinner = _instances()[0]
        degree = next(
            d for d in _drawn_degrees(svg_viewer) if d.instance_id == prinner.id
        )
        QTest.mouseClick(
            svg_viewer.view.viewport(),
            Qt.MouseButton.LeftButton,
            pos=svg_viewer.view.mapFromScene(degree.scenePos()),
        )
        assert svg_viewer.active_schema_instance == prinner.id
        assert svg_viewer.schema_palette.schema["name"] == "Prinner"

        drop_degree(svg_viewer, "note3-notehead0", schema="Prinner", stage=1)
        assert len(_instances()) == 2
        assert len(_instances()[0].degrees) == 2

    def test_palette_marks_placed_degrees(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0", stage=1, voice="lower")
        palette = svg_viewer.schema_palette
        assert palette.diagram.placed == {(1, "lower", 0)}
        assert "1 of 8" in palette.instance_label.text()

    def test_picking_other_schema_finishes_instance(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0")
        svg_viewer.schema_palette.select_schema("Meyer")
        assert svg_viewer.active_schema_instance is None

    def test_undo_creation_clears_active_instance(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0")
        commands.execute("edit.undo")
        assert _instances() == []
        assert svg_viewer.active_schema_instance is None
        # And the next drop starts a new instance instead of failing.
        drop_degree(svg_viewer, "note2-notehead0")
        assert len(_instances()) == 1


class TestPersistence:
    def test_instances_survive_reload(self, svg_viewer, tmp_path):
        drop_degree(svg_viewer, "note1-notehead0", stage=0)
        drop_degree(svg_viewer, "note2-notehead0", stage=1)
        before = [(i.schema, i.degrees) for i in _instances()]

        save_and_reopen(tmp_path)

        assert [(i.schema, i.degrees) for i in _instances()] == before
        assert len(_drawn_degrees(_viewer())) == 2

    def test_instance_keeps_its_own_copy_of_the_schema(self, svg_viewer, tmp_path):
        drop_degree(svg_viewer, "note1-notehead0")
        prinner = library.get_schema("Prinner")
        library.save_schema(prinner | {"color": "#000000"})

        save_and_reopen(tmp_path)

        assert _instances()[0].schema["color"] == "#a7ffeb"


class TestPalette:
    def test_toolbar_button_toggles_palette(self, svg_viewer):
        assert not svg_viewer.schema_palette.isVisible()
        commands.execute("timeline.score.toggle_schemata")
        assert svg_viewer.schema_palette.isVisible()
        commands.execute("timeline.score.toggle_schemata")
        assert not svg_viewer.schema_palette.isVisible()

    def test_drag_from_palette_onto_score(self, svg_viewer):
        commands.execute("timeline.score.toggle_schemata")
        palette = svg_viewer.schema_palette
        palette.select_schema("Prinner")
        diagram = palette.diagram
        center = diagram.degree_center(2, "lower", 0).toPoint()

        dragged = []

        def fake_exec(drag, *_):
            # QDrag.exec runs its own event loop, which tests can't drive.
            dragged.append(drag.mimeData())
            return Qt.DropAction.CopyAction

        with patch.object(QDrag, "exec", fake_exec):
            QTest.mousePress(diagram, Qt.MouseButton.LeftButton, pos=center)
            QTest.mouseMove(diagram, center + QPoint(20, 20))
            QTest.mouseRelease(diagram, Qt.MouseButton.LeftButton, pos=center)

        (mime,) = dragged
        assert json.loads(bytes(mime.data(DEGREE_MIME_TYPE)).decode()) == {
            "schema": "Prinner",
            "stage": 2,
            "voice": "lower",
            "index": 0,
            "value": 2,
            "accidental": "=",
        }
        _drop(svg_viewer, mime, _viewport_pos(svg_viewer, "note2-notehead0"))
        assert _instances()[0].degrees[0]["value"] == 2

    def test_palette_lists_library(self, svg_viewer):
        combo = svg_viewer.schema_palette.combo
        names = [combo.itemData(i) for i in range(combo.count()) if combo.itemData(i)]
        assert names == [s["name"] for s in library.get_schemata()]

    def test_palette_follows_library_changes(self, svg_viewer):
        prinner = library.get_schema("Prinner")
        library.save_schema(prinner | {"name": "My Prinner", "variant_of": "Prinner"})
        combo = svg_viewer.schema_palette.combo
        assert combo.findData("My Prinner") >= 0

    def test_instance_from_another_library_is_shown(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0")
        instance = _instances()[0]
        foreign = instance.schema | {"name": "Their Prinner"}
        get(
            Get.TIMELINE_UI_BY_ATTR, "timeline_class", ScoreTimeline
        ).timeline.set_component_data(instance.id, "schema", foreign)
        svg_viewer.set_active_schema_instance(instance.id)
        palette = svg_viewer.schema_palette
        assert palette.schema["name"] == "Their Prinner"
        assert "(from file)" in palette.combo.currentText()


class TestLayoutOnScore:
    """Degrees are drawn around the system, never over the notes."""

    def test_circles_stay_off_the_staves(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0", stage=0, voice="upper")
        drop_degree(svg_viewer, "note2-notehead0", stage=1, voice="lower")
        system = svg_viewer.system_rect
        for degree in _drawn_degrees(svg_viewer):
            assert not degree.sceneBoundingRect().intersects(system)
        upper, lower = sorted(_drawn_degrees(svg_viewer), key=lambda d: d.y())
        assert upper.placed["voice"] == "upper"
        assert upper.sceneBoundingRect().bottom() < system.top()
        assert lower.sceneBoundingRect().top() > system.bottom()

    def test_circle_stands_at_its_note(self, svg_viewer):
        drop_degree(svg_viewer, "note2-notehead0")
        (degree,) = _drawn_degrees(svg_viewer)
        assert degree.x() == pytest.approx(
            svg_viewer.noteheads["note2-notehead0"][0].center().x()
        )

    def test_ring_marks_the_note(self, svg_viewer):
        drop_degree(svg_viewer, "note2-notehead0")
        (drawn,) = svg_viewer.schema_instances.values()
        (halo,) = drawn.halos
        notehead = svg_viewer.noteheads["note2-notehead0"][0]
        assert halo.rect().contains(notehead)
        assert halo.brush().style() == Qt.BrushStyle.NoBrush

    def test_shared_note_gets_one_ring_per_instance(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0", schema="Prinner")
        drop_degree(svg_viewer, "note1-notehead0", schema="Meyer")
        rings = [
            h.rect() for d in svg_viewer.schema_instances.values() for h in d.halos
        ]
        small, large = sorted(rings, key=lambda r: r.width())
        assert large.contains(small) and large != small

    def test_instances_apart_share_a_row(self, svg_viewer):
        drop_degree(svg_viewer, "note0-notehead0", schema="Prinner")
        drop_degree(svg_viewer, "note3-notehead0", schema="Meyer")
        a, b = _drawn_degrees(svg_viewer)
        assert a.y() == b.y()

    def test_lines_run_along_the_row(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0", stage=0)
        drop_degree(svg_viewer, "note2-notehead0", stage=1)
        (drawn,) = svg_viewer.schema_instances.values()
        (line,) = drawn.lines
        assert not line.sceneBoundingRect().intersects(svg_viewer.system_rect)


def _score_tlui():
    return get(Get.TIMELINE_UI_BY_ATTR, "timeline_class", ScoreTimeline)


def _lane_elements():
    return sorted(
        _score_tlui().element_manager.get_elements_by_attribute(
            "kind", ComponentKind.SCHEMA_INSTANCE
        ),
        key=lambda e: e.id,
    )


class TestSchemaLane:
    def test_no_lane_without_instances(self, svg_viewer):
        tlui = _score_tlui()
        assert tlui.get_schema_lane_height() == 0
        assert tlui.get_height() == tlui.get_staves_height()

    def test_instance_gets_a_bar(self, svg_viewer):
        tlui = _score_tlui()
        drop_degree(svg_viewer, "note1-notehead0", stage=0)
        with undoable():
            drop_degree(svg_viewer, "note2-notehead0", stage=1)
            (element,) = _lane_elements()
            assert element.spans == [(1.0, 2.0)]
            (body,) = element.bodies
            assert body.rect().left() == pytest.approx(
                time_x_converter.get_x_by_time(1.0)
            )
            assert body.rect().right() == pytest.approx(
                time_x_converter.get_x_by_time(2.0)
            )
            assert body.rect().top() >= tlui.get_staves_height()
            assert tlui.get_height() == (
                tlui.get_staves_height() + tlui.get_schema_lane_height()
            )
            assert tlui.view.height() == tlui.get_height()

    def test_overlapping_instances_take_two_rows(self, svg_viewer):
        tlui = _score_tlui()
        drop_degree(svg_viewer, "note0-notehead0", schema="Prinner", stage=0)
        drop_degree(svg_viewer, "note2-notehead0", schema="Prinner", stage=1)
        one_row = tlui.get_height()
        drop_degree(svg_viewer, "note1-notehead0", schema="Meyer", stage=0)
        drop_degree(svg_viewer, "note3-notehead0", schema="Meyer", stage=1)
        assert sorted(e.row for e in _lane_elements()) == [0, 1]
        assert tlui.get_height() == one_row + tlui.SCHEMA_ROW_HEIGHT

    def test_instances_apart_share_a_row(self, svg_viewer):
        drop_degree(svg_viewer, "note0-notehead0", schema="Prinner", stage=0)
        drop_degree(svg_viewer, "note1-notehead0", schema="Prinner", stage=1)
        drop_degree(svg_viewer, "note2-notehead0", schema="Meyer", stage=0)
        drop_degree(svg_viewer, "note3-notehead0", schema="Meyer", stage=1)
        assert [e.row for e in _lane_elements()] == [0, 0]

    def test_bar_follows_degrees(self, svg_viewer):
        drop_degree(svg_viewer, "note1-notehead0", stage=0)
        drop_degree(svg_viewer, "note2-notehead0", stage=1)
        drop_degree(svg_viewer, "note3-notehead0", stage=2)
        last = svg_viewer.notehead_times("note3-notehead0")[0]
        assert last > 2.0
        assert _lane_elements()[0].spans == [(1.0, last)]

    def test_deleting_instance_removes_lane(self, svg_viewer):
        tlui = _score_tlui()
        drop_degree(svg_viewer, "note1-notehead0")
        commands.execute("timeline.score.delete_schema_instance")
        assert _lane_elements() == []
        assert tlui.get_schema_lane_height() == 0

    def test_clicking_bar_continues_instance_and_seeks(self, svg_viewer, tilia_state):
        drop_degree(svg_viewer, "note2-notehead0", schema="Prinner")
        commands.execute("timeline.score.finish_schema_instance")
        tilia_state.current_time = 0
        (element,) = _lane_elements()
        body = element.bodies[0]
        click_timeline_ui_view(
            element.timeline_ui.view,
            "left",
            body.rect().center().x(),
            body.rect().center().y(),
            body,
        )
        assert svg_viewer.active_schema_instance == element.id
        assert tilia_state.current_time == pytest.approx(2.0)
        assert element.is_selected()

    def test_bars_survive_reload(self, svg_viewer, tmp_path):
        drop_degree(svg_viewer, "note1-notehead0", stage=0)
        drop_degree(svg_viewer, "note2-notehead0", stage=1)
        save_and_reopen(tmp_path)
        (element,) = _lane_elements()
        assert element.spans == [(1.0, 2.0)]
        assert len(element.bodies) == 1
