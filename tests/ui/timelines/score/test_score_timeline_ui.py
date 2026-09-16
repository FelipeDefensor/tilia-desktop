import json

import pytest
from PySide6.QtGui import QColor

from tests.constants import EXAMPLE_MULTISTAFF_MUSICXML_PATH
from tests.mock import (
    Serve,
    patch_file_dialog,
    patch_yes_no_or_cancel_mb,
    patch_yes_or_no_dialog,
)
from tests.ui.timelines.interact import press_key
from tests.utils import (
    get_blank_file_data,
    get_command_action,
    get_main_window_menu,
    get_submenu,
    reloadable,
    undoable,
)
from tilia.errors import SCORE_STAFF_ID_ERROR
from tilia.parsers.score.musicxml import notes_from_musicXML
from tilia.requests import Get, Post, get, post
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.score.components import Clef
from tilia.timelines.score.timeline import ScoreTimeline
from tilia.ui import commands
from tilia.ui.windows import WindowKind


def test_create(tluis):
    with Serve(Get.FROM_USER_STRING, (True, "")):
        commands.execute("timelines.add.score")

    assert len(tluis) == 1


def test_create_note(score_tlui, note):
    assert score_tlui[0]


def test_set_note_color(score_tlui, note_ui):
    # Note bodies are created lazily on this post; without it,
    # set_color has no body to update and the test would crash.
    post(Post.SCORE_TIMELINE_COMPONENTS_DESERIALIZED, score_tlui.id)
    score_tlui.select_element(note_ui)

    with Serve(Get.FROM_USER_COLOR, (True, QColor("#123456"))):
        commands.execute("timeline.component.set_color")

    assert note_ui.get_data("color") == "#123456"


def test_reset_note_color(score_tlui, note_ui):
    post(Post.SCORE_TIMELINE_COMPONENTS_DESERIALIZED, score_tlui.id)
    score_tlui.select_element(note_ui)

    with Serve(Get.FROM_USER_COLOR, (True, QColor("#123456"))):
        commands.execute("timeline.component.set_color")

    commands.execute("timeline.component.reset_color")

    assert note_ui.get_data("color") is None


def test_create_staff(score_tlui, staff):
    assert score_tlui[0]


@pytest.mark.parametrize("shorthand", Clef.Shorthand)
def test_create_clef(score_tlui, shorthand):
    score_tlui.create_component(ComponentKind.CLEF, 0, 0, shorthand=shorthand)
    assert score_tlui[0]


def test_create_barline(score_tlui, bar_line):
    assert score_tlui[0]


def test_create_time_signature(score_tlui, time_signature):
    assert score_tlui[0]


@pytest.mark.parametrize("fifths", range(-7, 8))
def test_create_key_signature(score_tlui, fifths):
    score_tlui.create_component(
        ComponentKind.CLEF, 0, 0, shorthand=Clef.Shorthand.TREBLE
    )
    score_tlui.create_component(ComponentKind.KEY_SIGNATURE, 0, 0, fifths)
    assert score_tlui[0]


def _check_attrs(tmp_path, items_per_attr):
    @reloadable(tmp_path / "file.tla")
    def check_attrs() -> None:
        score = get(Get.TIMELINE_UI_BY_ATTR, "timeline_class", ScoreTimeline)
        for cmp_kind in (
            ComponentKind.CLEF,
            ComponentKind.KEY_SIGNATURE,
            ComponentKind.TIME_SIGNATURE,
        ):
            components = score.timeline.get_components_by_attr("KIND", cmp_kind)
            staff_no_to_y = {
                cmp.staff_index: score.get_element(cmp.id).body.y()
                for cmp in components
            }
            sorted_y = [
                k for k, _ in sorted(staff_no_to_y.items(), key=lambda item: item[1])
            ]
            assert len(sorted_y) == items_per_attr
            for i in range(len(sorted_y)):
                assert i == sorted_y[i]

    return check_attrs


def test_attribute_positions(qtui, score_tl, beat_tl, tmp_path):
    beat_tl.beat_pattern = [1]
    for i in range(0, 3):
        beat_tl.create_beat(i)
    beat_tl.measure_numbers = [0, 1, 2]
    beat_tl.recalculate_measures()

    notes_from_musicXML(score_tl, beat_tl, EXAMPLE_MULTISTAFF_MUSICXML_PATH)

    _check_attrs(tmp_path, items_per_attr=3)


def test_attribute_positions_without_measure_zero(qtui, score_tl, beat_tl, tmp_path):
    beat_tl.beat_pattern = [1]
    for i in range(1, 3):
        beat_tl.create_beat(i)
    beat_tl.measure_numbers = [1, 2]
    beat_tl.recalculate_measures()

    with patch_yes_or_no_dialog(False):
        notes_from_musicXML(score_tl, beat_tl, EXAMPLE_MULTISTAFF_MUSICXML_PATH)

    _check_attrs(tmp_path, items_per_attr=3)


def test_correct_clef_to_staff(qtui, score_tl, beat_tl):
    beat_tl.beat_pattern = [1]
    for i in range(1, 3):
        beat_tl.create_beat(i)
    beat_tl.measure_numbers = [1, 2]
    beat_tl.recalculate_measures()

    with patch_yes_or_no_dialog(False):
        notes_from_musicXML(score_tl, beat_tl, EXAMPLE_MULTISTAFF_MUSICXML_PATH)

    clefs = score_tl.get_components_by_attr("KIND", ComponentKind.CLEF)
    staff_no_to_clef = {clef.staff_index: clef.icon for clef in clefs}
    assert "alto" in staff_no_to_clef[0]
    assert "treble" in staff_no_to_clef[1]
    assert "bass" in staff_no_to_clef[2]


def test_missing_staff_deletes_timeline(qtui, tls, tilia_errors, tmp_path):
    file_data = get_blank_file_data()
    file_data["timelines"] = {
        0: {
            "kind": "Score",
            "height": 1,
            "is_visible": True,
            "name": "",
            "ordinal": 1,
            "svg_data": "",
            "viewer_beat_x": {},
            "hash": "",
            "components": {
                2: {
                    "staff_index": 0,
                    "time": 0,
                    "line_number": -1,
                    "step": 4,
                    "octave": 4,
                    "icon": "clef-treble",
                    "kind": "CLEF",
                    "hash": "",
                },
                3: {
                    "start": 0,
                    "end": 1,
                    "step": 0,
                    "accidental": 0,
                    "octave": 3,
                    "staff_index": 0,
                    "color": None,
                    "comments": "",
                    "display_accidental": False,
                    "kind": "NOTE",
                    "hash": "",
                },
            },
            "components_hash": "",
        }
    }
    file_data["media_metadata"]["media length"] = 1

    tmp_file = tmp_path / "test.tla"
    tmp_file.write_text(json.dumps(file_data), encoding="utf-8")

    with patch_file_dialog(True, [tmp_file]):
        commands.execute("file.open")

    tilia_errors.assert_in_error_title(SCORE_STAFF_ID_ERROR.title)
    assert tls.get_timeline_by_type(ScoreTimeline) is None


def test_duplicate_staff_deletes_timeline(qtui, tls, tilia_errors, tmp_path):
    file_data = get_blank_file_data()
    file_data["timelines"] = {
        0: {
            "kind": "Score",
            "height": 1,
            "is_visible": True,
            "name": "",
            "ordinal": 1,
            "svg_data": "",
            "viewer_beat_x": {},
            "hash": "",
            "components": {
                1: {"line_count": 5, "index": 0, "kind": "STAFF", "hash": ""},
                2: {"line_count": 5, "index": 0, "kind": "STAFF", "hash": ""},
            },
            "components_hash": "",
        }
    }

    tmp_file = tmp_path / "test.tla"
    tmp_file.write_text(json.dumps(file_data), encoding="utf-8")

    with patch_file_dialog(True, [tmp_file]):
        commands.execute("file.open")

    tilia_errors.assert_in_error_title(SCORE_STAFF_ID_ERROR.title)
    assert tls.get_timeline_by_type(ScoreTimeline) is None


def test_symbol_staff_collision(qtui, tmp_path):
    file_data_with_symbols = get_blank_file_data()
    file_data_with_symbols["timelines"] = {
        0: {
            "kind": "Score",
            "height": 1,
            "is_visible": True,
            "name": "",
            "ordinal": 1,
            "svg_data": "",
            "viewer_beat_x": {},
            "hash": "",
            "components": {
                1: {"line_count": 5, "index": 0, "kind": "STAFF", "hash": ""},
                2: {
                    "staff_index": 0,
                    "time": 0,
                    "line_number": -1,
                    "step": 4,
                    "octave": 4,
                    "icon": "clef-treble",
                    "kind": "CLEF",
                    "hash": "",
                },
            },
            "components_hash": "",
        }
    }

    tmp_file_with_symbols = tmp_path / "test_with_sym.tla"
    tmp_file_with_symbols.write_text(
        json.dumps(file_data_with_symbols), encoding="utf-8"
    )

    with patch_file_dialog(True, [tmp_file_with_symbols]):
        commands.execute("file.open")

    score = get(Get.TIMELINE_UI_BY_ATTR, "timeline_class", ScoreTimeline)
    clef = score.timeline.get_component_by_attr("KIND", ComponentKind.CLEF)
    staff = score.timeline.get_component_by_attr("KIND", ComponentKind.STAFF)

    staff_top_y_with_symbols = (
        score.get_element(staff.id).staff_lines.lines[0].line().y1()
    )

    assert score.get_element(clef.id).body.y() != staff_top_y_with_symbols

    file_data_sans_symbols = get_blank_file_data()
    file_data_sans_symbols["timelines"] = {
        0: {
            "kind": "Score",
            "height": 1,
            "is_visible": True,
            "name": "",
            "ordinal": 1,
            "svg_data": "",
            "viewer_beat_x": {},
            "hash": "",
            "components": {
                1: {"line_count": 5, "index": 0, "kind": "STAFF", "hash": ""},
            },
            "components_hash": "",
        }
    }

    tmp_file_sans_symbols = tmp_path / "test_sans_sym.tla"
    tmp_file_sans_symbols.write_text(
        json.dumps(file_data_sans_symbols), encoding="utf-8"
    )

    with (
        patch_file_dialog(True, [tmp_file_sans_symbols]),
        patch_yes_no_or_cancel_mb(False),  # do not save changes
    ):
        commands.execute("file.open")

    score = get(Get.TIMELINE_UI_BY_ATTR, "timeline_class", ScoreTimeline)
    staff = score.timeline.get_component_by_attr("KIND", ComponentKind.STAFF)

    staff_top_y_sans_symbols = (
        score.get_element(staff.id).staff_lines.lines[0].line().y1()
    )

    assert staff_top_y_sans_symbols < staff_top_y_with_symbols


def _add_score_action(qtui):
    add_menu = get_submenu(get_main_window_menu(qtui, "Timelines"), "Add")
    return get_command_action(add_menu, "timelines.add.score")


def test_create_score_timeline_from_menu_bar_R333(qtui, tluis):
    # R333: create a score timeline from the menu bar (Timelines > Add > Score).
    action = _add_score_action(qtui)
    assert action is not None

    with Serve(Get.FROM_USER_STRING, (True, "")):
        with undoable():
            action.trigger()

    assert len(tluis) == 1
    assert len(tluis.get_timeline_uis_by_type(ScoreTimeline)) == 1


def test_create_several_score_timelines_from_menu_bar_R334(qtui, tluis):
    # R334: create several score timelines from the menu bar.
    action = _add_score_action(qtui)

    with Serve(Get.FROM_USER_STRING, (True, "")):
        for _ in range(3):
            action.trigger()

    score_tluis = tluis.get_timeline_uis_by_type(ScoreTimeline)
    assert len(score_tluis) == 3
    assert len({tlui.id for tlui in score_tluis}) == 3


def _create_two_notes(score_tl):
    score_tl.create_component(ComponentKind.STAFF, 0, 5)
    score_tl.create_component(ComponentKind.CLEF, 0, 0, shorthand=Clef.Shorthand.TREBLE)
    note1 = score_tl.create_component(ComponentKind.NOTE, 0, 1, 0, 0, 3, 0)[0]
    note2 = score_tl.create_component(ComponentKind.NOTE, 1, 2, 2, 0, 3, 0)[0]
    return note1, note2


def test_set_color_of_several_notes_R349(score_tlui, score_tl):
    # R349: set the color of several notes at once (context menu / set_color command).
    note1, note2 = _create_two_notes(score_tl)
    post(Post.SCORE_TIMELINE_COMPONENTS_DESERIALIZED, score_tlui.id)

    note1_ui = score_tlui.get_component_ui(note1)
    note2_ui = score_tlui.get_component_ui(note2)
    score_tlui.select_element(note1_ui)
    score_tlui.select_element(note2_ui)

    with Serve(Get.FROM_USER_COLOR, (True, QColor("#123456"))):
        commands.execute("timeline.component.set_color")

    assert note1_ui.get_data("color") == "#123456"
    assert note2_ui.get_data("color") == "#123456"


def test_reset_color_of_several_notes_R341(score_tlui, score_tl):
    # R341: reset the color of several notes at once (context menu / reset_color command).
    note1, note2 = _create_two_notes(score_tl)
    post(Post.SCORE_TIMELINE_COMPONENTS_DESERIALIZED, score_tlui.id)

    note1_ui = score_tlui.get_component_ui(note1)
    note2_ui = score_tlui.get_component_ui(note2)
    score_tlui.select_element(note1_ui)
    score_tlui.select_element(note2_ui)

    with Serve(Get.FROM_USER_COLOR, (True, QColor("#123456"))):
        commands.execute("timeline.component.set_color")

    commands.execute("timeline.component.reset_color")

    assert note1_ui.get_data("color") is None
    assert note2_ui.get_data("color") is None


def test_delete_note_keyboard_shortcut_does_nothing_R343(score_tlui, score_tl, note_ui):
    # R343: deleting a note with the keyboard shortcut does nothing -- notes
    # can't be deleted (score components carry TimelineFlag.COMPONENTS_NOT_DELETABLE).
    post(Post.SCORE_TIMELINE_COMPONENTS_DESERIALIZED, score_tlui.id)
    score_tlui.select_element(note_ui)
    component_count_before = len(score_tl)

    press_key("Delete")

    assert len(score_tl) == component_count_before
    assert note_ui.tl_component in score_tl


def test_open_inspector_for_note_with_keyboard_shortcut_R344(qtui, score_tlui, note_ui):
    # R344: open the inspector for a note with the keyboard shortcut (Enter/Return).
    post(Post.SCORE_TIMELINE_COMPONENTS_DESERIALIZED, score_tlui.id)
    score_tlui.select_element(note_ui)
    press_key("Return")

    assert qtui.is_window_open(WindowKind.INSPECT)
    post(Post.WINDOW_CLOSE, WindowKind.INSPECT)


def test_reload_file_places_notes_in_same_position_R346(
    qtui, score_tl, beat_tl, tmp_path
):
    # R346: load an annotation (.tla) file -- notes are placed in about the
    # same place as before saving. Reading: "annotation file" = the app's own
    # .tla project file (TiLiA = "TimeLine Annotator"); "same place" = same
    # vertical (pitch/staff-derived) position for every note, mirroring how
    # test_attribute_positions above checks CLEF/KEY_SIGNATURE/TIME_SIGNATURE
    # by Y position only -- time-axis (X) placement is not asserted there
    # either, since it is derived from time_x_converter's view-width-dependent
    # scale rather than from saved data.
    beat_tl.beat_pattern = [1]
    for i in range(0, 3):
        beat_tl.create_beat(i)
    beat_tl.measure_numbers = [0, 1, 2]
    beat_tl.recalculate_measures()

    notes_from_musicXML(score_tl, beat_tl, EXAMPLE_MULTISTAFF_MUSICXML_PATH)

    def _note_y_positions():
        score = get(Get.TIMELINE_UI_BY_ATTR, "timeline_class", ScoreTimeline)
        notes = sorted(
            score.timeline.get_components_by_attr("KIND", ComponentKind.NOTE)
        )
        assert notes  # sanity: the fixture score has notes to compare
        return [score.get_element(n.id).top_y for n in notes]

    positions_before = _note_y_positions()

    @reloadable(tmp_path / "file.tla")
    def check_positions():
        assert _note_y_positions() == positions_before


def test_import_score_with_no_beat_timeline_shows_error_R348(score_tlui, tilia_errors):
    # R348: importing a score with no beat timeline in the file shows an error.
    commands.execute("timelines.import.score")
    tilia_errors.assert_in_error_title("Import failed")


def test_import_score_then_delete_all_beats_does_not_crash_R354(
    qtui, score_tl, beat_tl, beat_tlui, tmp_path
):
    # R354: import a score, then delete all beats: no crash. This covers the
    # data-layer half of the row -- clicking a note in the rendered score
    # viewer afterwards needs rendering (see report) and isn't covered here.
    beat_tl.beat_pattern = [1]
    for i in range(0, 3):
        beat_tl.create_beat(i)
    beat_tl.measure_numbers = [0, 1, 2]
    beat_tl.recalculate_measures()

    notes_from_musicXML(score_tl, beat_tl, EXAMPLE_MULTISTAFF_MUSICXML_PATH)
    note = score_tl.get_component_by_attr("KIND", ComponentKind.NOTE)
    assert note is not None

    with patch_yes_or_no_dialog(True):
        commands.execute("timeline.clear", beat_tlui)

    assert len(beat_tl) == 0

    score = get(Get.TIMELINE_UI_BY_ATTR, "timeline_class", ScoreTimeline)
    note_ui = score.get_element(note.id)
    # Metric position depends on the beat timeline; with no beats left this
    # should degrade to None rather than raise.
    assert note_ui.get_data("start_metric_position") is None


@pytest.mark.skip(
    reason=(
        "R342: needs rendering. 'Click a note: playback seeks to it, and the "
        "viewer's highlight rectangle moves with the selection' is about the "
        "rendered score notation in the SvgViewer window, not the timeline's "
        "own NoteUI. The seek-on-click behaviour lives in "
        "SvgStaveNote.mouseDoubleClickEvent (tilia/ui/windows/svg_viewer.py), "
        "and SvgStaveNote items only exist once real SVG note glyphs have "
        "been produced by the QWebEngineView-based musicxml_to_svg renderer "
        "(tilia/parsers/score/musicxml_to_svg.py:39). Every existing score "
        "test uses svg_data='' and there's no synchronous test harness for "
        "that async renderer, so this can't be exercised in the offscreen "
        "pytest session without faking the rendered SVG, which isn't allowed."
    )
)
def test_click_note_in_score_viewer_seeks_and_moves_highlight_R342():
    pass
