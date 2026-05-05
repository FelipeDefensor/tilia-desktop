from PySide6.QtWidgets import QComboBox, QSpinBox

from tilia.requests import Post, post
from tilia.settings import settings
from tilia.timelines.audiowave.constants import FRAMES_PER_PEAK_OPTIONS
from tilia.ui.windows import WindowKind


def _open_settings(qtui):
    post(Post.WINDOW_OPEN, WindowKind.SETTINGS)
    return qtui._windows[WindowKind.SETTINGS]


class TestFramesPerPeakDropdown:
    def test_renders_as_combobox(self, qtui):
        window = _open_settings(qtui)
        widget = window.settings["audiowave_timeline"]["frames_per_peak"]
        assert isinstance(widget, QComboBox)

    def test_default_height_still_renders_as_spinbox(self, qtui):
        # Sanity: only frames_per_peak is converted to a combobox.
        window = _open_settings(qtui)
        widget = window.settings["audiowave_timeline"]["default_height"]
        assert isinstance(widget, QSpinBox)

    def test_options_match_constants(self, qtui):
        window = _open_settings(qtui)
        widget = window.settings["audiowave_timeline"]["frames_per_peak"]
        items = [widget.itemData(i) for i in range(widget.count())]
        assert items == FRAMES_PER_PEAK_OPTIONS

    def test_current_value_matches_setting(self, qtui):
        window = _open_settings(qtui)
        widget = window.settings["audiowave_timeline"]["frames_per_peak"]
        assert widget.currentData() == settings.get(
            "audiowave_timeline", "frames_per_peak"
        )

    def test_apply_persists_int_value(self, qtui):
        window = _open_settings(qtui)
        widget = window.settings["audiowave_timeline"]["frames_per_peak"]
        target = next(v for v in FRAMES_PER_PEAK_OPTIONS if v != widget.currentData())
        widget.setCurrentIndex(widget.findData(target))
        window.apply_fields()
        assert settings.get("audiowave_timeline", "frames_per_peak") == target
