"""Table-driven wiring tests for release-checklist rows that differ from a
sibling row only by the ROUTE used to reach a command (Edit menu / keyboard
shortcut / context menu / toolbar button / menu bar). Behaviour of each
command is tested elsewhere (see the per-kind UI test modules); this module
only asserts, per route:

1. presence  - the action/button/shortcut exists (shortcut strings are
   pinned, so an accidental rebind fails on purpose).
2. firing    - triggering the route runs the expected command.
3. completeness - no command that has a shortcut, or sits in one of the
   menus/context-menus/toolbars exercised below, is missing from this
   table (test_N01_guard_command_coverage), and no two of those shortcuts
   collide unresolvably (test_N01_guard_no_ambiguous_shortcuts).

Row IDs refer to the original manual release-checklist sheet. Many sheet
rows collapse onto the same (route, command) pair -- e.g. "paste multiple"
vs "paste single", or "delete one beat" vs "delete several beats" -- since
that distinction is a *behaviour* difference the callback handles, not a
different route. Those rows share one test, whose id lists every row it
covers (e.g. "R053+R079-..."). Ids starting with "N01" belong to the proposed
checklist row N01 ("every command reachable from its menu, toolbar, context
menu and shortcut"): routes that are not on the sheet, plus the two guards.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from typing import NamedTuple
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton

import tilia.ui.commands as commands
from tests.mock import Serve, patch_yes_or_no_dialog
from tests.ui.timelines.interact import press_key
from tests.utils import (
    get_command_action,
    get_command_from_toolbar,
    get_command_names,
    get_main_window_menu,
)
from tilia.requests import Get
from tilia.ui.commands import CommandQAction
from tilia.ui.menus import EditMenu, ViewMenu
from tilia.ui.timelines.beat.context_menu import BeatContextMenu
from tilia.ui.timelines.hierarchy.context_menu import HierarchyContextMenu
from tilia.ui.timelines.hierarchy.toolbar import HierarchyTimelineToolbar
from tilia.ui.timelines.pdf.context_menu import PdfMarkerContextMenu
from tilia.ui.timelines.score.context_menu import NoteContextMenu
from tilia.ui.windows import WindowKind

pytestmark = pytest.mark.usefixtures("qtui", "tluis")


# --------------------------------------------------------------------------
# Firing helpers
# --------------------------------------------------------------------------


@contextmanager
def spy_command(name: str):
    """Temporarily wrap the callback registered under `name` (see
    commands.execute -> _name_to_callback) with a Mock that still calls
    through. Behaviour is unaffected, but we can assert that a route
    resolved to *this* command specifically -- the thing a copy-pasted
    registration could get wrong.
    """
    original = commands._name_to_callback[name]
    mock = Mock(wraps=original)
    commands._name_to_callback[name] = mock
    try:
        yield mock
    finally:
        # Re-registration would already restore this, but tests can fail
        # before that happens; always leave the real callback in place.
        commands._name_to_callback[name] = original


def fire(action):
    """Trigger a QAction as a click would. Qt's .trigger() is a no-op on a
    disabled action, which would be a false negative for wiring purposes
    (enablement is application *behaviour*, tested elsewhere) -- so force
    it enabled first.
    """
    action.setEnabled(True)
    action.trigger()


# --------------------------------------------------------------------------
# Context-menu routes: instantiate the element's context-menu class
# directly (CLAUDE.md: "Context menus: test both presence AND behavior"),
# find the action, fire it.
# --------------------------------------------------------------------------


class ContextMenuCase(NamedTuple):
    id: str
    kind: str  # "pdf" | "beat" | "hierarchy" | "score"
    command: str
    needs_selection: bool = False
    needs_int_dialog: bool = False
    needs_color_dialog: bool = False


CONTEXT_MENU_CASES = [
    ContextMenuCase("R080-context-menu-pdf-paste", "pdf", "timeline.component.paste"),
    ContextMenuCase(
        "R075-context-menu-pdf-inspect",
        "pdf",
        "timeline.element.inspect",
        needs_selection=True,
    ),
    ContextMenuCase(
        "R193+R195-context-menu-beat-delete", "beat", "timeline.component.delete"
    ),
    ContextMenuCase(
        "R198-context-menu-beat-distribute", "beat", "timeline.beat.distribute"
    ),
    ContextMenuCase(
        "R286-context-menu-hierarchy-copy", "hierarchy", "timeline.component.copy"
    ),
    ContextMenuCase(
        "R288-context-menu-hierarchy-paste", "hierarchy", "timeline.component.paste"
    ),
    # No needs_selection here: NoteUI.on_select() dereferences a `.body`
    # that only exists once the score viewer has actually rendered SVG
    # note glyphs (see the note_ui fixture, which creates the backend
    # component only). That's unrelated to wiring: the spy below records
    # the call at commands.execute's boundary regardless of what
    # on_timeline_element_inspect's own selection guard then does with it.
    ContextMenuCase(
        "R345-context-menu-score-inspect",
        "score",
        "timeline.element.inspect",
    ),
    # --- NEW: same menus as the rows above, remaining items -----------
    ContextMenuCase(
        "N01-context-menu-hierarchy-set-color",
        "hierarchy",
        "timeline.component.set_color",
        needs_color_dialog=True,
    ),
    ContextMenuCase(
        "N01-context-menu-hierarchy-reset-color",
        "hierarchy",
        "timeline.component.reset_color",
    ),
    ContextMenuCase(
        "N01-context-menu-hierarchy-export-audio",
        "hierarchy",
        "timeline.hierarchy.export_audio",
    ),
    ContextMenuCase(
        "N01-context-menu-hierarchy-add-pre-start",
        "hierarchy",
        "timeline.hierarchy.add_pre_start",
    ),
    ContextMenuCase(
        "N01-context-menu-hierarchy-add-post-end",
        "hierarchy",
        "timeline.hierarchy.add_post_end",
    ),
    ContextMenuCase(
        "N01-context-menu-beat-set-measure-number",
        "beat",
        "timeline.beat.set_measure_number",
        needs_int_dialog=True,
    ),
    ContextMenuCase(
        "N01-context-menu-beat-reset-measure-number",
        "beat",
        "timeline.beat.reset_measure_number",
    ),
    ContextMenuCase(
        "N01-context-menu-beat-set-amount-in-measure",
        "beat",
        "timeline.beat.set_amount_in_measure",
        needs_int_dialog=True,
    ),
]

_CONTEXT_MENU_CLASSES = {
    "pdf": PdfMarkerContextMenu,
    "beat": BeatContextMenu,
    "hierarchy": HierarchyContextMenu,
    "score": NoteContextMenu,
}


def _build_element(
    kind, pdf_tlui, beat_tlui, hierarchy_tlui, note_ui, score_tlui, tilia_state
):
    """Return (tlui, element) for `kind`, with just enough state that the
    element's full, unconditional context-menu item set is present (in
    particular: hierarchy's add_pre_start/add_post_end, which only show up
    with room on both sides -- see HierarchyContextMenu.__init__).
    """
    if kind == "pdf":
        commands.execute("timeline.pdf.add")
        return pdf_tlui, pdf_tlui[0]
    if kind == "beat":
        commands.execute("timeline.beat.add")
        return beat_tlui, beat_tlui[0]
    if kind == "hierarchy":
        tilia_state.duration = 100
        commands.execute("timeline.hierarchy.add", start=10, end=20, level=2)
        return hierarchy_tlui, hierarchy_tlui[0]
    assert kind == "score"
    return score_tlui, note_ui


@pytest.mark.parametrize(
    "case", CONTEXT_MENU_CASES, ids=[c.id for c in CONTEXT_MENU_CASES]
)
def test_context_menu_route(
    case, pdf_tlui, beat_tlui, hierarchy_tlui, note_ui, score_tlui, tilia_state
):
    tlui, element = _build_element(
        case.kind, pdf_tlui, beat_tlui, hierarchy_tlui, note_ui, score_tlui, tilia_state
    )
    menu = _CONTEXT_MENU_CLASSES[case.kind](element)

    action = get_command_action(menu, case.command)
    assert action is not None, (
        f"{case.command!r} not found in {type(menu).__name__} "
        f"(items: {get_command_names(menu)})"
    )

    if case.needs_selection:
        tlui.select_element(element)

    if case.needs_int_dialog:
        dialog_ctx = Serve(Get.FROM_USER_INT, (True, 1))
    elif case.needs_color_dialog:
        dialog_ctx = Serve(Get.FROM_USER_COLOR, (True, QColor("#000000")))
    else:
        dialog_ctx = nullcontext()
    with dialog_ctx, spy_command(case.command) as spy:
        fire(action)
    spy.assert_called()


# --------------------------------------------------------------------------
# Keyboard-shortcut routes (main-window scoped: Ctrl+C/V, Ctrl+Shift+V, g).
# Shortcut strings are pinned via QKeySequence equality.
# --------------------------------------------------------------------------


class ShortcutCase(NamedTuple):
    id: str
    key: str
    modifier: Qt.KeyboardModifier
    command: str
    shortcut_text: str


SHORTCUT_CASES = [
    ShortcutCase(
        "R055+R057+R083+R086+R289-shortcut-paste",
        "v",
        Qt.KeyboardModifier.ControlModifier,
        "timeline.component.paste",
        "Ctrl+V",
    ),
    ShortcutCase(
        "R287-shortcut-copy",
        "c",
        Qt.KeyboardModifier.ControlModifier,
        "timeline.component.copy",
        "Ctrl+C",
    ),
    ShortcutCase(
        "R293-shortcut-paste-complete",
        "v",
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        "timeline.component.paste_complete",
        "Ctrl+Shift+V",
    ),
    ShortcutCase(
        "R275-shortcut-group",
        "g",
        Qt.KeyboardModifier.NoModifier,
        "timeline.hierarchy.group",
        "g",
    ),
]


@pytest.mark.parametrize("case", SHORTCUT_CASES, ids=[c.id for c in SHORTCUT_CASES])
def test_shortcut_route(case, hierarchy_tlui):
    action = commands.get_qaction(case.command)
    assert action.shortcut() == QKeySequence(case.shortcut_text)

    # A selected hierarchy element gives every one of these commands a
    # valid target (copy/paste/paste_complete/group all act on selection).
    commands.execute("timeline.hierarchy.add", start=0, end=1, level=1)
    hierarchy_tlui.select_element(hierarchy_tlui[0])

    action.setEnabled(True)
    with spy_command(case.command) as spy:
        press_key(case.key, modifier=case.modifier)
    spy.assert_called()


def test_R282_shortcut_increase_level(hierarchy_tlui):
    """Ctrl+Up has no QAction shortcut. increase_level/decrease_level are
    dispatched from TimelineView.keyPressEvent via
    Post.TIMELINE_KEY_PRESS_CTRL_UP/DOWN (see hierarchy/timeline.py
    register_commands: attaching them to the QAction as well would trigger
    Qt's "Ambiguous shortcut overload"). There is no separate static
    structure to assert "presence" against, so presence and firing are
    asserted together by sending the real key event to the timeline view.
    """
    commands.execute("timeline.hierarchy.add", start=0, end=1, level=1)
    hierarchy_tlui.select_element(hierarchy_tlui[0])

    with spy_command("timeline.hierarchy.increase_level") as spy:
        QTest.keyClick(
            hierarchy_tlui.view, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier
        )
    spy.assert_called()


# --------------------------------------------------------------------------
# Main-window menu routes (Edit / View / Timelines).
# --------------------------------------------------------------------------


class MenuCase(NamedTuple):
    id: str
    menu_name: str
    command: str


MENU_CASES = [
    MenuCase("R053+R079-edit-menu-paste", "Edit", "timeline.component.paste"),
    MenuCase("R369-menu-bar-zoom-in", "View", "view.zoom.in"),
    MenuCase("R372-menu-bar-zoom-out", "View", "view.zoom.out"),
    MenuCase("N01-edit-menu-undo", "Edit", "edit.undo"),
    MenuCase("N01-edit-menu-redo", "Edit", "edit.redo"),
    MenuCase("N01-edit-menu-open-settings", "Edit", "window.open.settings"),
    MenuCase(
        "N01-timelines-menu-open-manage-timelines",
        "Timelines",
        "window.open.manage_timelines",
    ),
]


@pytest.mark.parametrize("case", MENU_CASES, ids=[c.id for c in MENU_CASES])
def test_main_window_menu_route(case, qtui):
    menu = get_main_window_menu(qtui, case.menu_name)
    action = get_command_action(menu, case.command)
    assert action is not None, (
        f"{case.command!r} not found in {case.menu_name!r} menu "
        f"(items: {get_command_names(menu)})"
    )

    with spy_command(case.command) as spy:
        fire(action)
    spy.assert_called()


# --------------------------------------------------------------------------
# Toolbar-button routes (per-timeline-kind toolbar).
# --------------------------------------------------------------------------

TOOLBAR_CASES = [
    ("R315-toolbar-hierarchy-split", "timeline.hierarchy.split"),
    ("N01-toolbar-hierarchy-merge", "timeline.hierarchy.merge"),
    ("N01-toolbar-hierarchy-decrease-level", "timeline.hierarchy.decrease_level"),
    ("N01-toolbar-hierarchy-create-child", "timeline.hierarchy.create_child"),
]


@pytest.mark.parametrize(
    "test_id,command", TOOLBAR_CASES, ids=[c[0] for c in TOOLBAR_CASES]
)
def test_hierarchy_toolbar_route(test_id, command, hierarchy_tlui):
    # Two adjacent level-1 elements: a valid target for split/merge/
    # decrease_level/create_child regardless of which one this case fires.
    commands.execute("timeline.hierarchy.add", start=0, end=1, level=2)
    commands.execute("timeline.hierarchy.add", start=1, end=2, level=2)
    hierarchy_tlui.select_element(hierarchy_tlui[0])
    hierarchy_tlui.select_element(hierarchy_tlui[1])

    action = get_command_from_toolbar(hierarchy_tlui, command)
    assert action is not None, f"{command!r} not found on HierarchyTimelineToolbar"

    with spy_command(command) as spy:
        fire(action)
    spy.assert_called()


# --------------------------------------------------------------------------
# Manage Timelines window (a plain QPushButton, not a QAction/shortcut).
# --------------------------------------------------------------------------


def test_R215_manage_timelines_delete(hierarchy_tlui, qtui):
    commands.execute("window.open.manage_timelines")
    dialog = qtui._windows[WindowKind.MANAGE_TIMELINES]
    list_widget = dialog.list_widget

    for i in range(list_widget.count()):
        if list_widget.item(i).timeline_ui == hierarchy_tlui:
            list_widget.setCurrentRow(i)
            break
    else:
        pytest.fail("hierarchy timeline not listed in Manage Timelines")

    assert dialog.delete_button.isEnabled()
    with patch_yes_or_no_dialog(True), spy_command("timeline.delete") as spy:
        QTest.mouseClick(dialog.delete_button, Qt.MouseButton.LeftButton)
    spy.assert_called()


# --------------------------------------------------------------------------
# Score viewer: a per-instance toolbar (QToolButtons in a QVBoxLayout, not
# a QToolBar/QMenu, so get_command_action doesn't apply directly) plus two
# real QAction shortcuts scoped to the viewer widget.
# --------------------------------------------------------------------------


def _find_toolbutton(svg_viewer, command_name):
    for button in svg_viewer.findChildren(QToolButton):
        action = button.defaultAction()
        if isinstance(action, CommandQAction) and action.command_name == command_name:
            return button
    return None


SCORE_VIEWER_TOOLBAR_CASES = [
    ("R378-score-viewer-add", "timeline.score.add"),
    ("R379-score-viewer-delete", "timeline.score.delete"),
    ("R381-score-viewer-edit", "timeline.score.edit"),
]


@pytest.mark.parametrize(
    "test_id,command",
    SCORE_VIEWER_TOOLBAR_CASES,
    ids=[c[0] for c in SCORE_VIEWER_TOOLBAR_CASES],
)
def test_score_viewer_toolbar_route(test_id, command, score_tlui):
    svg_viewer = score_tlui.svg_view
    button = _find_toolbutton(svg_viewer, command)
    assert button is not None, f"{command!r} not found on score viewer toolbar"

    with spy_command(command) as spy:
        button.defaultAction().setEnabled(True)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    spy.assert_called()


SCORE_VIEWER_SHORTCUT_CASES = [
    ("R385-score-viewer-font-inc", "timeline.score.font_inc", "Shift+Up"),
    ("R386-score-viewer-font-dec", "timeline.score.font_dec", "Shift+Down"),
]


@pytest.mark.parametrize(
    "test_id,command,shortcut_text",
    SCORE_VIEWER_SHORTCUT_CASES,
    ids=[c[0] for c in SCORE_VIEWER_SHORTCUT_CASES],
)
def test_score_viewer_shortcut_route(test_id, command, shortcut_text, score_tlui):
    action = commands.get_qaction(command)
    assert action.shortcut() == QKeySequence(shortcut_text)

    svg_viewer = score_tlui.svg_view
    # The viewer is built lazily (ScoreTimelineUI.svg_view) and, unlike
    # ManageTimelines/other windows, isn't shown or docked as a side
    # effect -- an invisible/windowless widget never becomes Qt's "active
    # window", so its WindowShortcut-context action never activates.
    svg_viewer.show()
    QApplication.processEvents()

    key = shortcut_text.rsplit("+", 1)[-1]
    action.setEnabled(True)
    with spy_command(command) as spy:
        QTest.keyClick(
            svg_viewer, getattr(Qt.Key, f"Key_{key}"), Qt.KeyboardModifier.ShiftModifier
        )
    spy.assert_called()


# --------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------

# Every command name this module already fires and asserts on, above.
COVERED_COMMANDS = (
    {c.command for c in CONTEXT_MENU_CASES}
    | {c.command for c in SHORTCUT_CASES}
    | {c.command for c in MENU_CASES}
    | {command for _, command in TOOLBAR_CASES}
    | {command for _, command in SCORE_VIEWER_TOOLBAR_CASES}
    | {command for _, command, _ in SCORE_VIEWER_SHORTCUT_CASES}
    | {"timeline.hierarchy.increase_level", "timeline.delete"}
)


def test_N01_guard_command_coverage(
    pdf_tlui, beat_tlui, hierarchy_tlui, note_ui, score_tlui, tilia_state
):
    """Every command reachable from the menus/context-menus/toolbars this
    module exercises must appear in COVERED_COMMANDS above. A future
    command added to one of *these same* surfaces without a matching test
    row makes this fail and names the gap.

    Scope is deliberately the surfaces the 28 checklist rows already touch
    (Edit/View menus; the Marker/PDF/Beat/Hierarchy/Score element context
    menus; the Hierarchy toolbar; the score viewer's toolbar) -- not the
    whole application. File/Help menus, the per-kind Add/Import submenus,
    and the Range/Harmony/Audiowave/Slider timeline kinds belong to other
    sections of the release checklist; see the report for the full list
    a whole-application version of this guard would additionally require.
    """
    required: set[str] = set()
    required |= set(get_command_names(EditMenu()))
    required |= set(get_command_names(ViewMenu()))

    tlui, pdf_element = _build_element(
        "pdf", pdf_tlui, beat_tlui, hierarchy_tlui, note_ui, score_tlui, tilia_state
    )
    required |= set(get_command_names(PdfMarkerContextMenu(pdf_element)))

    _, beat_element = _build_element(
        "beat", pdf_tlui, beat_tlui, hierarchy_tlui, note_ui, score_tlui, tilia_state
    )
    required |= set(get_command_names(BeatContextMenu(beat_element)))

    _, hierarchy_element = _build_element(
        "hierarchy",
        pdf_tlui,
        beat_tlui,
        hierarchy_tlui,
        note_ui,
        score_tlui,
        tilia_state,
    )
    required |= set(get_command_names(HierarchyContextMenu(hierarchy_element)))
    required |= set(get_command_names(HierarchyTimelineToolbar()))

    required |= set(get_command_names(NoteContextMenu(note_ui)))

    svg_viewer = score_tlui.svg_view
    for button in svg_viewer.findChildren(QToolButton):
        action = button.defaultAction()
        if isinstance(action, CommandQAction):
            required.add(action.command_name)

    missing = required - COVERED_COMMANDS
    assert not missing, f"commands missing a wiring test: {sorted(missing)}"


def test_N01_guard_no_ambiguous_shortcuts():
    """No two actions active in the same window may share a live Qt
    shortcut -- Qt silently ignores the ambiguous one. The app already
    resolves *known* cross-kind collisions (e.g. hierarchy vs range both
    binding "s" to split) into a single QShortcut dispatched by
    TimelineUIs.on_shared_shortcut_fired, which itself refuses to dispatch
    (AMBIGUOUS_SHORTCUT) unless every bound name is `timeline.<kind>.*`
    with a distinct <kind>. This mirrors that same validation statically,
    across every registered shortcut, so a genuinely new collision fails
    here instead of silently misfiring at runtime.
    """
    for shortcut, names in commands._shortcut_to_commands.items():
        if len(names) <= 1:
            continue
        seen_kind_prefixes: dict[str, str] = {}
        for name in names:
            assert name.startswith("timeline."), (
                f"Shortcut {shortcut!r} bound to a non-timeline command "
                f"among a collision: {names}"
            )
            kind_prefix = ".".join(name.split(".", 2)[:2])
            assert kind_prefix not in seen_kind_prefixes, (
                f"Shortcut {shortcut!r} bound to two commands of the same "
                f"kind (unresolvable -- no 'most recently clicked' "
                f"tiebreaker applies): {names}"
            )
            seen_kind_prefixes[kind_prefix] = name
