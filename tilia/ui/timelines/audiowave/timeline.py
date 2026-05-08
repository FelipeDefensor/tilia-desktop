from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsItem

from tilia.requests import Get, Post, get, listen
from tilia.timelines.audiowave.timeline import AudioWaveTimeline
from tilia.ui import commands
from tilia.ui.coords import time_x_converter
from tilia.ui.timelines.audiowave.element import WaveformElement
from tilia.ui.timelines.base.timeline import TimelineUI


class AudioWaveTimelineUI(TimelineUI):
    ELEMENT_CLASS = WaveformElement
    timeline_class = AudioWaveTimeline

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Track frames_per_peak so we can detect *that specific* setting
        # changing — only it invalidates the cached LOD pyramid and warrants
        # a full re-extraction. Color/height changes just need a repaint.
        self._last_frames_per_peak = self.timeline.frames_per_peak
        self._setup_requests()

    def _setup_requests(self):
        listen(self, Post.PLAYER_URL_CHANGED, lambda _: self.timeline.refresh())
        listen(self, Post.SETTINGS_UPDATED, self.on_settings_updated)

    def on_settings_updated(self, updated_settings):
        if "audiowave_timeline" not in updated_settings:
            return
        get(Get.TIMELINE_COLLECTION).set_timeline_data(
            self.id, "height", self.timeline.default_height
        )
        current_fpp = self.timeline.frames_per_peak
        if current_fpp != self._last_frames_per_peak:
            self._last_frames_per_peak = current_fpp
            self.timeline.refresh()
        else:
            # paint() reads default_color from settings on every call, so a
            # repaint is enough — no need to redo the heavy extraction.
            for element in self.elements:
                element.body.update()

    def on_left_click(
        self,
        item: QGraphicsItem,
        modifier: Qt.KeyboardModifier,
        double: bool,
        x: int,
        y: int,
    ) -> None:
        # Audacity-style: clicking anywhere on the waveform seeks playback
        # to that time.  No selection, no inspector — the waveform is read-only.
        # Single click is gated on if_playing=False (so a stray click during
        # playback doesn't disrupt it); double click is an explicit gesture and
        # always seeks. Mirrors slider/timeline.py.
        if not self.get_item_owner(item):
            return
        time = time_x_converter.get_time_by_x(x)
        if double:
            commands.execute("media.seek", time)
        else:
            commands.execute("media.seek", time, if_playing=False)
