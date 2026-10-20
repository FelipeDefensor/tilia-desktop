import pytest
from PySide6.QtWidgets import QDialog, QDialogButtonBox

from tilia.settings import settings
from tilia.timelines.score.schema import starter_schemata
from tilia.ui.schema import library
from tilia.ui.schema.editor import SchemaEditor, edit_schema


@pytest.fixture(autouse=True)
def no_custom_schemata():
    settings.set_custom_schemata([])


def names():
    return [s["name"] for s in library.get_schemata()]


class TestLibrary:
    def test_starters(self):
        assert sorted(names()) == sorted(s["name"] for s in starter_schemata())

    def test_sorted_by_family_then_name(self):
        assert names().index("Romanesca (leaping)") + 1 == names().index(
            "Romanesca (stepwise)"
        )
        assert names().index("Do-Re-Mi") < names().index("Prinner")

    def test_save_custom(self):
        schema = library.get_schema("Prinner") | {"name": "Modulating Prinner"}
        library.save_schema(schema)
        assert library.get_schema("Modulating Prinner") == schema
        assert library.is_custom("Modulating Prinner")

    def test_custom_replaces_starter(self):
        library.save_schema(library.get_schema("Prinner") | {"color": "#000000"})
        assert library.get_schema("Prinner")["color"] == "#000000"
        assert names().count("Prinner") == 1

    def test_deleting_custom_brings_starter_back(self):
        library.save_schema(library.get_schema("Prinner") | {"color": "#000000"})
        library.delete_schema("Prinner")
        assert library.get_schema("Prinner")["color"] == "#a7ffeb"

    def test_renaming_drops_old_name(self):
        library.save_schema(library.get_schema("Prinner") | {"name": "A"})
        library.save_schema(library.get_schema("A") | {"name": "B"}, replaces="A")
        assert "A" not in names()
        assert "B" in names()

    def test_invalid_schema_is_not_saved(self):
        with pytest.raises(ValueError):
            library.save_schema({"name": "Broken"})

    def test_unreadable_store_reads_as_no_custom_schemata(self):
        settings._settings.setValue(settings.CUSTOM_SCHEMATA_KEY, "{not json")
        assert sorted(names()) == sorted(s["name"] for s in starter_schemata())

    def test_invalid_stored_schema_is_skipped(self):
        settings.set_custom_schemata([{"name": "Broken"}])
        assert "Broken" not in names()

    def test_get_returns_a_copy(self):
        library.get_schema("Prinner")["stages"].clear()
        assert library.get_schema("Prinner")["stages"]


def save_button(editor):
    return editor.buttons.button(QDialogButtonBox.StandardButton.Save)


class TestEditor:
    def test_new_schema_needs_a_name(self, qtui):
        editor = SchemaEditor()
        assert not save_button(editor).isEnabled()
        assert "name" in editor.error.text()
        editor.name.setText("Lully")
        assert save_button(editor).isEnabled()

    def test_build_a_schema(self, qtui):
        editor = SchemaEditor()
        editor.name.setText("Converging cadence")
        editor.family.setCurrentText("Cadences")
        editor.add_stage_button.click()
        stage = editor.stage_editors[1]
        stage.add_buttons["lower"].click()
        stage = editor.stage_editors[1]  # rebuilt
        stage.degree_editors["lower"][0].value.setCurrentText("4")
        stage.degree_editors["lower"][0].accidental.setCurrentIndex(
            stage.degree_editors["lower"][0].accidental.findData("+")
        )
        stage.strength.setCurrentIndex(stage.strength.findData("S"))

        schema = editor.schema()
        assert schema["name"] == "Converging cadence"
        assert schema["variant_of"] == "Cadences"
        assert schema["stages"][1] == {
            "strength": "S",
            "upper": [],
            "inner": [],
            "lower": [{"value": 4, "accidental": "+", "voice": "lower"}],
        }
        assert editor.preview.schema == schema

    def test_stage_without_degrees_cannot_be_saved(self, qtui):
        editor = SchemaEditor()
        editor.name.setText("x")
        editor.add_stage_button.click()
        assert not save_button(editor).isEnabled()
        assert "Stage 2" in editor.error.text()

    def test_remove_degree_and_stage(self, qtui):
        editor = SchemaEditor(library.get_schema("Prinner"))
        remove_degree = (
            editor.stage_editors[0]
            .degree_editors["upper"][0]
            .findChild(type(editor.add_stage_button))
        )
        remove_degree.click()
        assert editor.schema()["stages"][0]["upper"] == []
        editor.stage_editors[3].findChildren(type(editor.add_stage_button))[0].click()
        assert len(editor.schema()["stages"]) == 3

    def test_new_name_must_be_free(self, qtui):
        editor = SchemaEditor()
        editor.name.setText("Prinner")
        assert not save_button(editor).isEnabled()
        assert "already" in editor.error.text()

    def test_editing_keeps_its_name(self, qtui):
        editor = SchemaEditor(library.get_schema("Prinner"))
        assert save_button(editor).isEnabled()

    def test_editing_does_not_change_the_original(self, qtui):
        prinner = library.get_schema("Prinner")
        editor = SchemaEditor(prinner)
        editor.add_stage_button.click()
        assert len(prinner["stages"]) == 4

    def test_edit_schema_saves_to_library(self, qtui, monkeypatch):
        def accept(dialog):
            dialog.name.setText("Prinner (minor)")
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(SchemaEditor, "exec", accept)
        saved = edit_schema(library.get_schema("Prinner"))
        assert saved["name"] == "Prinner (minor)"
        assert library.is_custom("Prinner (minor)")
        # The starter it was made from stays.
        assert library.get_schema("Prinner") is not None

    def test_cancel_saves_nothing(self, qtui, monkeypatch):
        monkeypatch.setattr(SchemaEditor, "exec", lambda _: QDialog.DialogCode.Rejected)
        assert edit_schema() is None
        assert sorted(names()) == sorted(s["name"] for s in starter_schemata())
