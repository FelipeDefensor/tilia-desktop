from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import soundfile

import tilia.errors
from tilia.log import logger
from tilia.requests import Get, Post, get, post
from tilia.settings import settings
from tilia.timelines.audiowave.peaks import (
    CancelToken,
    adapt_frames_per_peak,
    build_lod_pyramid,
    compute_peaks_async,
    estimate_pyramid_bytes,
)
from tilia.timelines.base.timeline import (
    Timeline,
    TimelineComponentManager,
    TimelineFlag,
)
from tilia.timelines.component_kinds import ComponentKind

if TYPE_CHECKING:
    from tilia.timelines.audiowave.components import Waveform


class AudioWaveTLComponentManager(TimelineComponentManager):
    def __init__(self, timeline: AudioWaveTimeline) -> None:
        super().__init__(timeline, [ComponentKind.AUDIOWAVE])


class AudioWaveTimeline(Timeline):
    COMPONENT_MANAGER_CLASS = AudioWaveTLComponentManager
    FLAGS = [
        TimelineFlag.NOT_CLEARABLE,
        TimelineFlag.NOT_EXPORTABLE,
        TimelineFlag.COMPONENTS_NOT_EDITABLE,
        TimelineFlag.COMPONENTS_NOT_DELETABLE,
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pending_cancel: CancelToken | None = None
        # `_pending_signals` keeps the QObject alive so its signal->slot
        # connection survives until the worker emits.
        self._pending_signals: Any = None

    @property
    def default_height(self) -> int:
        return settings.get("audiowave_timeline", "default_height")

    @property
    def frames_per_peak(self) -> int:
        return int(settings.get("audiowave_timeline", "frames_per_peak"))

    @property
    def waveform_component(self) -> "Waveform | None":
        components = self.components
        return components[0] if components else None

    def refresh(self) -> None:
        self._cancel_pending_computation()
        self.clear()

        path = get(Get.MEDIA_PATH)
        if not path:
            self._update_visibility(False)
            return

        try:
            with soundfile.SoundFile(path) as af:
                samplerate = af.samplerate
                total_frames = af.frames
        except Exception:
            tilia.errors.display(tilia.errors.AUDIOWAVE_INVALID_FILE)
            self._update_visibility(False)
            return

        self._update_visibility(True)
        fpp = adapt_frames_per_peak(total_frames, self.frames_per_peak)
        if fpp != self.frames_per_peak:
            mb = estimate_pyramid_bytes(total_frames, self.frames_per_peak) / (
                1024 * 1024
            )
            logger.warning(
                "audiowave pyramid for %s would need ~%.0f MB at "
                "frames_per_peak=%d; bumping to %d to fit memory budget.",
                path,
                mb,
                self.frames_per_peak,
                fpp,
            )
        component, _ = self.create_component(
            ComponentKind.AUDIOWAVE,
            samplerate=samplerate,
            total_frames=total_frames,
            frames_per_peak=fpp,
        )
        if component is None:
            return
        self._launch_peak_computation(path, component)

    def _launch_peak_computation(self, path: str, component: "Waveform") -> None:
        cancel, signals = compute_peaks_async(
            path,
            component.frames_per_peak,
            on_done=lambda mins, maxs, sr, tf: self._on_peaks_ready(
                component, mins, maxs, sr, tf
            ),
            on_error=lambda exc: self._on_peaks_error(),
        )
        self._pending_cancel = cancel
        self._pending_signals = signals

    def _on_peaks_ready(
        self,
        component: "Waveform",
        peaks_min: np.ndarray,
        peaks_max: np.ndarray,
        samplerate: int,
        total_frames: int,
    ) -> None:
        if component not in self.components:
            return
        component.samplerate = int(samplerate)
        component.total_frames = int(total_frames)
        component.lod_min, component.lod_max = build_lod_pyramid(
            peaks_min, peaks_max
        )
        component.is_ready = True
        post(Post.AUDIOWAVE_PEAKS_READY, self.id, component.id)

    def _on_peaks_error(self) -> None:
        tilia.errors.display(tilia.errors.AUDIOWAVE_INVALID_FILE)
        self._update_visibility(False)

    def _cancel_pending_computation(self) -> None:
        if self._pending_cancel is not None:
            self._pending_cancel.cancelled = True
        self._pending_cancel = None
        self._pending_signals = None

    def deserialize_components(self, components: dict[int, dict[str, Any]]) -> None:
        is_legacy = any(
            isinstance(c, dict) and "amplitude" in c
            for c in components.values()
        )
        if is_legacy:
            self.refresh()
            return
        super().deserialize_components(components)
        path = get(Get.MEDIA_PATH)
        component = self.waveform_component
        if component is not None and path:
            self._launch_peak_computation(path, component)

    def _update_visibility(self, is_visible: bool) -> None:
        if self.get_data("is_visible") != is_visible:
            self.set_data("is_visible", is_visible)
            post(Post.TIMELINE_SET_DATA_DONE, self.id, "is_visible", is_visible)

    def scale(self, factor: float) -> None:
        # refresh will be called when new media is loaded
        pass

    def crop(self, factor: float) -> None:
        # refresh will be called when new media is loaded
        pass
