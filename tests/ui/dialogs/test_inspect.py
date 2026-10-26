import pytest
from PySide6.QtCore import Qt

from tests.conftest import parametrize_ui_element
from tests.ui.timelines.harmony.interact import click_harmony_ui
from tests.ui.timelines.harmony.test_harmony_timeline_ui import add_harmony
from tests.ui.timelines.interact import press_key
from tilia.requests import Post, post
from tilia.ui import commands
from tilia.ui.timelines.beat import BeatUI
from tilia.ui.windows.kinds import WindowKind


@parametrize_ui_element
def test_inspect_elements(tluis, element, request):
    element = request.getfixturevalue(element)
    element.timeline_ui.select_element(element)

    commands.execute("timeline.element.inspect")


@parametrize_ui_element
def test_inspect_elements_with_beat_timeline(element, beat_tlui, request):
    # some properties are only displayed if a beat timeline is present
    element = request.getfixturevalue(element)
    if not isinstance(element, BeatUI):
        for i in range(10):
            beat_tlui.create_beat(i)

    element.timeline_ui.select_element(element)

    commands.execute("timeline.element.inspect")


class TestInspectComboBox:
    @pytest.fixture(autouse=True)
    def close_inspector(self):
        yield
        post(Post.WINDOW_CLOSE, WindowKind.INSPECT)

    def open_inspector_for(self, tlui, element_ui, qtui):
        tlui.select_element(element_ui)
        commands.execute("timeline.element.inspect")
        return qtui._windows[WindowKind.INSPECT]

    def test_combobox_sends_data_not_index(self, qtui, harmony_tlui):
        harmony, _ = harmony_tlui.create_harmony(accidental=0)
        harmony_ui = harmony_tlui.get_element(harmony.id)
        inspector = self.open_inspector_for(harmony_tlui, harmony_ui, qtui)

        inspector.field_name_to_widgets["Accidental"][1].setCurrentIndex(2)

        assert harmony_ui.get_data("accidental") == -1

    def test_combobox_displays_correct_item_for_current_value(self, qtui, harmony_tlui):
        # When accidental=-1 ("♭"), the combobox must show index 2, not index 1.
        harmony, _ = harmony_tlui.create_harmony(accidental=-1)
        harmony_ui = harmony_tlui.get_element(harmony.id)
        inspector = self.open_inspector_for(harmony_tlui, harmony_ui, qtui)

        assert inspector.field_name_to_widgets["Accidental"][1].currentData() == -1


class TestTimelineShortcutsWithInspectorFocused:
    @pytest.fixture(autouse=True)
    def close_inspector(self):
        yield
        post(Post.WINDOW_CLOSE, WindowKind.INSPECT)

    @staticmethod
    def focus_step_combo_box(harmony_ui, qtui):
        click_harmony_ui(harmony_ui)
        commands.execute("timeline.element.inspect")
        combo_box = qtui._windows[WindowKind.INSPECT].field_name_to_widgets["Step"][1]
        combo_box.setFocus()
        return combo_box

    @staticmethod
    def focus_timeline_view(qtui):
        # Clicks in tests are posted straight to the timeline, so they don't
        # move the focus the way a real click on the timeline view does.
        qtui.timeline_uis.view.setFocus()

    def test_delete_does_not_delete_harmony(self, qtui, harmony_tlui):
        add_harmony()
        self.focus_step_combo_box(harmony_tlui.harmonies()[0], qtui)

        press_key("Delete")

        assert len(harmony_tlui.harmonies()) == 1

    def test_paste_does_not_paste_into_harmony(self, qtui, harmony_tlui):
        add_harmony(step=0)
        commands.execute("media.seek", 10)
        add_harmony(step=1)
        click_harmony_ui(harmony_tlui.harmonies()[0])
        self.focus_timeline_view(qtui)
        press_key("C", Qt.KeyboardModifier.ControlModifier)
        self.focus_step_combo_box(harmony_tlui.harmonies()[1], qtui)

        press_key("V", Qt.KeyboardModifier.ControlModifier)

        assert [h.get_data("step") for h in harmony_tlui.harmonies()] == [0, 1]

    def test_delete_deletes_harmony_once_timeline_view_is_focused(
        self, qtui, harmony_tlui
    ):
        add_harmony()
        self.focus_step_combo_box(harmony_tlui.harmonies()[0], qtui)
        self.focus_timeline_view(qtui)

        press_key("Delete")

        assert harmony_tlui.is_empty

    def test_paste_pastes_into_harmony_once_timeline_view_is_focused(
        self, qtui, harmony_tlui
    ):
        add_harmony(step=0)
        commands.execute("media.seek", 10)
        add_harmony(step=1)
        click_harmony_ui(harmony_tlui.harmonies()[0])
        self.focus_timeline_view(qtui)
        press_key("C", Qt.KeyboardModifier.ControlModifier)
        self.focus_step_combo_box(harmony_tlui.harmonies()[1], qtui)
        self.focus_timeline_view(qtui)

        press_key("V", Qt.KeyboardModifier.ControlModifier)

        assert [h.get_data("step") for h in harmony_tlui.harmonies()] == [0, 0]
