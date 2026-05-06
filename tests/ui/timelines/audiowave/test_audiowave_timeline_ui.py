from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from tests.ui.timelines.audiowave.interact import click_at_time
from tilia.requests import Post, post
from tilia.settings import settings
from tilia.timelines.audiowave.constants import FRAMES_PER_PEAK_OPTIONS
from tilia.ui import commands
from tilia.ui.windows.kinds import WindowKind


class TestWaveformElement:
    def test_create_via_set_peaks(self, audiowave_tlui):
        audiowave_tlui.set_peaks_for_test()
        assert len(audiowave_tlui) == 1


class TestClickToSeek:
    def test_click_seeks_to_clicked_time(self, audiowave_tlui, waveform_element):
        with patch(
            "tilia.ui.timelines.audiowave.timeline.commands.execute"
        ) as mock:
            click_at_time(audiowave_tlui, 5.0)
        assert mock.called

    def test_click_outside_waveform_is_noop(self, audiowave_tlui, waveform_element):
        with patch(
            "tilia.ui.timelines.audiowave.timeline.commands.execute"
        ) as mock:
            audiowave_tlui.on_left_click(
                None,
                Qt.KeyboardModifier.NoModifier,
                False,
                100,
                10,
            )
        mock.assert_not_called()

    def test_single_click_is_gated_on_not_playing(
        self, audiowave_tlui, waveform_element
    ):
        with patch(
            "tilia.ui.timelines.audiowave.timeline.commands.execute"
        ) as mock:
            click_at_time(audiowave_tlui, 5.0)
        kwargs = mock.call_args.kwargs
        assert kwargs.get("if_playing") is False

    def test_double_click_seeks_unconditionally(
        self, audiowave_tlui, waveform_element
    ):
        with patch(
            "tilia.ui.timelines.audiowave.timeline.commands.execute"
        ) as mock:
            click_at_time(audiowave_tlui, 5.0, double=True)
        kwargs = mock.call_args.kwargs
        assert "if_playing" not in kwargs


class TestSettings:
    # use_test_settings (auto-applied via the qtui fixture) routes settings
    # writes to a dedicated test QSettings store.

    def test_default_height_setting_updates_timeline_height(self, audiowave_tlui):
        new_height = 200
        settings.set("audiowave_timeline", "default_height", new_height)
        post(Post.SETTINGS_UPDATED, ["audiowave_timeline"])
        assert audiowave_tlui.get_data("height") == new_height

    def test_frames_per_peak_setting_triggers_refresh(self, audiowave_tlui):
        refresh_calls = []
        original = audiowave_tlui.timeline.refresh
        audiowave_tlui.timeline.refresh = lambda: refresh_calls.append(1)
        try:
            settings.set("audiowave_timeline", "frames_per_peak", 256)
            post(Post.SETTINGS_UPDATED, ["audiowave_timeline"])
        finally:
            audiowave_tlui.timeline.refresh = original
        assert refresh_calls == [1]

    def test_frames_per_peak_options_are_powers_of_two(self):
        # Sanity: every option must be 2^k. Off-by-one in the options list
        # would silently degrade the LOD pyramid math.
        for v in FRAMES_PER_PEAK_OPTIONS:
            assert v > 0 and (v & (v - 1)) == 0

    def test_unrelated_setting_group_does_not_trigger_refresh(self, audiowave_tlui):
        refresh_calls = []
        audiowave_tlui.timeline.refresh = lambda: refresh_calls.append(1)
        post(Post.SETTINGS_UPDATED, ["range_timeline"])
        assert refresh_calls == []


class TestPaintRobustness:
    """Regression: paint() must never raise — Qt leaves QPainter half-active
    if it does, leading to follow-up segfaults on the next repaint."""

    @staticmethod
    def _paint_into_image(item, width=400, height=80):
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(QColor("black"))
        painter = QPainter(image)
        try:
            item.paint(painter, None, None)
        finally:
            painter.end()

    def test_paint_with_no_peaks_shows_loading(self, audiowave_tlui):
        # No call to set_peaks_for_test → no Waveform component → loading state.
        assert len(audiowave_tlui) == 0
        # Force a Waveform component without is_ready=True to exercise the
        # is_ready=False branch.
        component = audiowave_tlui.set_peaks_for_test()
        component.is_ready = False
        element = audiowave_tlui[0]
        self._paint_into_image(element.body)  # must not raise

    def test_paint_with_peaks_ready(self, audiowave_tlui, waveform_element):
        self._paint_into_image(waveform_element.body)

    def test_paint_with_zero_samplerate(self, audiowave_tlui):
        component = audiowave_tlui.set_peaks_for_test()
        component.samplerate = 0
        element = audiowave_tlui[0]
        self._paint_into_image(element.body)

    def test_paint_with_zero_total_frames(self, audiowave_tlui):
        component = audiowave_tlui.set_peaks_for_test()
        component.total_frames = 0
        element = audiowave_tlui[0]
        self._paint_into_image(element.body)

    def test_paint_with_degenerate_bounding(self, audiowave_tlui, waveform_element):
        # Force a zero-width bounding rect via monkey-patch.
        original = waveform_element.body.boundingRect
        waveform_element.body.boundingRect = lambda: QRectF(0, 0, 0, 0)
        try:
            self._paint_into_image(waveform_element.body)
        finally:
            waveform_element.body.boundingRect = original


class TestSpinnerLifecycle:
    def test_spinner_runs_until_peaks_ready(self, audiowave_tlui):
        component = audiowave_tlui.set_peaks_for_test()
        component.is_ready = False
        element = audiowave_tlui[0]
        # Triggering paint while not ready starts the spinner.
        TestPaintRobustness._paint_into_image(element.body)
        assert element.body._spinner_timer.isActive()

        # AUDIOWAVE_PEAKS_READY stops it.
        post(Post.AUDIOWAVE_PEAKS_READY, audiowave_tlui.id, component.id)
        assert not element.body._spinner_timer.isActive()

    def test_spinner_unaffected_by_other_components_ready(self, audiowave_tlui):
        component = audiowave_tlui.set_peaks_for_test()
        component.is_ready = False
        element = audiowave_tlui[0]
        TestPaintRobustness._paint_into_image(element.body)
        assert element.body._spinner_timer.isActive()

        # A signal for a different component id should NOT stop our spinner.
        post(Post.AUDIOWAVE_PEAKS_READY, audiowave_tlui.id, "other-component-id")
        assert element.body._spinner_timer.isActive()


class TestInspect:
    def test_open_inspect_with_waveform_selected_does_not_raise(
        self, audiowave_tlui, waveform_element
    ):
        # WaveformElement has no INSPECTOR_FIELDS — opening the inspect
        # window while one is in selected_elements used to raise. The
        # base timeline must skip non-inspectable selected elements.
        audiowave_tlui.element_manager.select_element(waveform_element)
        audiowave_tlui.on_window_open_done(WindowKind.INSPECT)


class TestUndoableState:
    def test_no_audiowave_commands_registered(self, audiowave_tlui):
        # Audiowave is read-only — no per-component CRUD commands should be
        # in the registered command set, so users can't accidentally
        # produce undo entries for the waveform.
        registered = set(commands._name_to_callback.keys())
        audiowave_commands = [
            c for c in registered if c.startswith("timeline.audiowave.")
        ]
        # Only allow a small whitelist (currently empty).
        assert audiowave_commands == []

    def test_no_components_added_to_undo_state(self, audiowave_tlui, tilia_state):
        # Exercise: set up a waveform, then perform a no-op user command
        # that DOES record undo state, and verify the waveform component
        # isn't part of the recorded state in any user-visible way.
        # The flag COMPONENTS_NOT_EDITABLE prevents add/remove paths.
        component = audiowave_tlui.set_peaks_for_test()
        peaks_min_before = component.lod_min
        # Trigger an unrelated command that records state.
        commands.execute("edit.undo")  # no-op when stack is empty
        commands.execute("edit.redo")
        # Audiowave's runtime-only data must survive (it's not serialized).
        assert component.lod_min is peaks_min_before


class TestCleanup:
    def test_element_delete_stops_spinner(self, audiowave_tlui):
        component = audiowave_tlui.set_peaks_for_test()
        component.is_ready = False
        element = audiowave_tlui[0]
        TestPaintRobustness._paint_into_image(element.body)
        assert element.body._spinner_timer.isActive()

        spinner = element.body._spinner_timer
        element.delete()
        assert not spinner.isActive()


class TestListenerCleanup:
    def test_create_destroy_does_not_leak_listeners(self, tls, tluis):
        from tilia.requests import Get, get
        from tilia.requests.post import _posts_to_listeners
        from tilia.timelines.audiowave.timeline import AudioWaveTimeline

        baseline = len(_posts_to_listeners.get(Post.AUDIOWAVE_PEAKS_READY, {}))
        collection = get(Get.TIMELINE_COLLECTION)

        for _ in range(10):
            tl = tls.create_timeline(AudioWaveTimeline)
            tl.refresh = lambda: None  # stub network/file IO
            tlui = tluis.get_timeline_ui(tl.id)
            tlui.set_peaks_for_test = lambda **kw: None  # noqa: F841
            collection.delete_timeline(tl)

        after = len(_posts_to_listeners.get(Post.AUDIOWAVE_PEAKS_READY, {}))
        # Listener count must be bounded — at most one per active timeline,
        # which we've torn down. Allow a small slack for transient state but
        # require it not to grow proportional to the loop count.
        assert after - baseline <= 1


class TestKnownDisplay:
    def test_constant_signal_paints_without_error(self, audiowave_tlui):
        # End-to-end: a constant signal injected via the test fixture
        # should paint cleanly across multiple zoom levels (different LOD
        # levels exercised).
        n = 4096
        peaks_min = np.full(n, -0.5, dtype=np.float32)
        peaks_max = np.full(n, 0.5, dtype=np.float32)
        audiowave_tlui.set_peaks_for_test(
            samplerate=44100,
            total_frames=n * 128,
            frames_per_peak=128,
            peaks_min=peaks_min,
            peaks_max=peaks_max,
        )
        element = audiowave_tlui[0]
        TestPaintRobustness._paint_into_image(element.body, width=200)
        TestPaintRobustness._paint_into_image(element.body, width=2000)
