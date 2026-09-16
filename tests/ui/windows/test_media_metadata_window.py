from unittest.mock import patch

import pytest

from tests.mock import patch_yes_or_no_dialog
from tilia.requests import Post, post
from tilia.ui.windows import WindowKind
from tilia.ui.windows.metadata_edit_fields import EditMetadataFieldsDialog


@pytest.fixture
def media_metadata_window(qtui):
    post(Post.WINDOW_OPEN, WindowKind.MEDIA_METADATA)
    window = qtui._windows[WindowKind.MEDIA_METADATA]
    yield window
    with patch_yes_or_no_dialog(True):
        window.close()


def test_open(media_metadata_window):
    assert media_metadata_window


def test_close(qtui, media_metadata_window):
    media_metadata_window.close()
    assert not qtui.is_window_open(WindowKind.MEDIA_METADATA)


def test_edit_field_value(qtui, media_metadata_window, tilia_state):
    media_metadata_window.metadata["title"].setText("New Title")
    media_metadata_window.apply_fields()
    media_metadata_window.close()

    assert tilia_state.metadata["title"] == "New Title"


def test_do_not_confirm_close(qtui, media_metadata_window, tilia_state):
    prev_title = tilia_state.metadata["title"]
    media_metadata_window.metadata["title"].setText("New Title")
    with patch_yes_or_no_dialog(False):
        media_metadata_window.close()

    assert qtui.is_window_open(WindowKind.MEDIA_METADATA)
    assert tilia_state.metadata["title"] == prev_title


def test_confirm_close_discards_changes(qtui, media_metadata_window, tilia_state):
    prev_title = tilia_state.metadata["title"]
    media_metadata_window.metadata["title"].setText("New Title")
    with patch_yes_or_no_dialog(True):
        media_metadata_window.close()

    assert not qtui.is_window_open(WindowKind.MEDIA_METADATA)
    assert tilia_state.metadata["title"] == prev_title


def test_R105_close_with_unsaved_changes_and_do_not_confirm_keeps_changes_in_window(
    qtui, media_metadata_window, tilia_state
):
    prev_title = tilia_state.metadata["title"]
    media_metadata_window.metadata["title"].setText("New Title")
    with patch_yes_or_no_dialog(False):
        media_metadata_window.close()

    assert qtui.is_window_open(WindowKind.MEDIA_METADATA)
    # The in-progress edit is kept in the window, ready to be applied/saved
    # later, rather than being reverted just because the close was aborted.
    assert media_metadata_window.metadata["title"].text() == "New Title"
    assert tilia_state.metadata["title"] == prev_title


def _set_custom_fields(window, valid_fields, invalid_fields=None):
    """Drive the "Edit fields..." button, replacing the full custom-fields
    list with `valid_fields` -- mirrors what the user would get by editing
    the dialog's text box and clicking Ok."""
    with (
        patch.object(EditMetadataFieldsDialog, "exec", return_value=True),
        patch.object(
            EditMetadataFieldsDialog,
            "get_result",
            return_value=(valid_fields, invalid_fields or []),
        ),
    ):
        window.on_edit_metadata_fields_button()


def test_R107_adding_a_duplicate_field_does_not_add_it(
    media_metadata_window, tilia_state
):
    _set_custom_fields(media_metadata_window, ["r107_field", "r107_field"])

    assert list(tilia_state.metadata).count("r107_field") == 1


def test_R108_add_several_fields(media_metadata_window, tilia_state):
    _set_custom_fields(media_metadata_window, ["r108_field1", "r108_field2"])

    assert tilia_state.metadata["r108_field1"] == ""
    assert tilia_state.metadata["r108_field2"] == ""


def test_R109_add_one_field(media_metadata_window, tilia_state):
    _set_custom_fields(media_metadata_window, ["r109_field"])

    assert tilia_state.metadata["r109_field"] == ""


def test_R110_set_a_value_to_an_empty_string(media_metadata_window, tilia_state):
    media_metadata_window.metadata["composer"].setText("Some Composer")
    media_metadata_window.apply_fields()
    assert tilia_state.metadata["composer"] == "Some Composer"

    media_metadata_window.metadata["composer"].setText("")
    media_metadata_window.apply_fields()

    assert tilia_state.metadata["composer"] == ""


def test_R111_edit_several_values(media_metadata_window, tilia_state):
    media_metadata_window.metadata["composer"].setText("New Composer")
    media_metadata_window.metadata["tonality"].setText("D minor")
    media_metadata_window.apply_fields()

    assert tilia_state.metadata["composer"] == "New Composer"
    assert tilia_state.metadata["tonality"] == "D minor"


def test_R112_remove_all_fields(media_metadata_window, tilia_state):
    _set_custom_fields(media_metadata_window, ["r112_field1", "r112_field2"])
    assert "r112_field1" in tilia_state.metadata

    _set_custom_fields(media_metadata_window, [])

    assert "r112_field1" not in tilia_state.metadata
    assert "r112_field2" not in tilia_state.metadata
    # "composer" & co. are pre-populated *default* custom fields (see
    # settings["media_metadata"]["default_fields"]), not required ones, so
    # they are removed too. Only the truly required fields survive.
    assert "title" in tilia_state.metadata
    assert "notes" in tilia_state.metadata


def test_R113_remove_one_field(media_metadata_window, tilia_state):
    _set_custom_fields(media_metadata_window, ["r113_keep", "r113_remove"])

    _set_custom_fields(media_metadata_window, ["r113_keep"])

    assert "r113_keep" in tilia_state.metadata
    assert "r113_remove" not in tilia_state.metadata


def test_R114_remove_several_fields(media_metadata_window, tilia_state):
    _set_custom_fields(
        media_metadata_window, ["r114_keep", "r114_remove1", "r114_remove2"]
    )

    _set_custom_fields(media_metadata_window, ["r114_keep"])

    assert "r114_keep" in tilia_state.metadata
    assert "r114_remove1" not in tilia_state.metadata
    assert "r114_remove2" not in tilia_state.metadata


def test_R115_replace_a_field_rename(media_metadata_window, tilia_state):
    _set_custom_fields(media_metadata_window, ["r115_oldname"])
    media_metadata_window.metadata["r115_oldname"].setText("some value")
    media_metadata_window.apply_fields()
    assert tilia_state.metadata["r115_oldname"] == "some value"

    _set_custom_fields(media_metadata_window, ["r115_newname"])

    assert "r115_oldname" not in tilia_state.metadata
    assert "r115_newname" in tilia_state.metadata
    assert tilia_state.metadata["r115_newname"] == "some value"


@pytest.mark.parametrize(
    "new_fields",
    [
        pytest.param(["r115_b", "r115_c"], id="R113-remove-the-first-field"),
        pytest.param(
            ["r115_new", "r115_a", "r115_b", "r115_c"], id="R109-add-a-field-first"
        ),
        pytest.param(["r115_c", "r115_a", "r115_b"], id="reorder-fields"),
    ],
)
def test_editing_fields_keeps_each_value_under_its_own_name(
    media_metadata_window, tilia_state, new_fields
):
    # Renames are told apart from removals and additions by comparing the old
    # and new field lists; shifted positions must not move values between fields.
    old_fields = ["r115_a", "r115_b", "r115_c"]
    _set_custom_fields(media_metadata_window, old_fields)
    for name in old_fields:
        media_metadata_window.metadata[name].setText(f"{name} value")
    media_metadata_window.apply_fields()

    _set_custom_fields(media_metadata_window, new_fields)

    for name in old_fields:
        if name in new_fields:
            assert tilia_state.metadata[name] == f"{name} value"
    assert all(
        tilia_state.metadata[name] == ""
        for name in new_fields
        if name not in old_fields
    )
