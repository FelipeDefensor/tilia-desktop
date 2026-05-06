from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import numpy as np
import soundfile

import tilia.constants
import tilia.errors
from tilia.log import logger
from tilia.requests import Get, Post, get, post
from tilia.settings import settings
from tilia.timelines.audiowave import cache as pyramid_cache
from tilia.timelines.audiowave.extract import (
    extract_peaks_via_ffmpeg,
    is_ffmpeg_available,
)
from tilia.timelines.audiowave.peaks import (
    CancelToken,
    adapt_frames_per_peak,
    build_lod_pyramid,
    compute_peaks_async,
    compute_peaks_sync,
    estimate_pyramid_bytes,
)
from tilia.timelines.audiowave.youtube import (
    YTDownloadError,
    YTNetworkError,
    YTUnavailableError,
    acknowledge_terms_or_cancel,
    extract_peaks_via_yt_dlp,
    get_video_id,
    is_yt_dlp_available,
)
from tilia.timelines.base.timeline import (
    Timeline,
    TimelineComponentManager,
    TimelineFlag,
)
from tilia.timelines.component_kinds import ComponentKind

if TYPE_CHECKING:
    from tilia.timelines.audiowave.components import Waveform


_AUDIO_ONLY_EXTENSIONS = {"wav", "ogg", "mp3", "flac", "aac"}


def _is_youtube(path: str) -> bool:
    return bool(re.match(tilia.constants.YOUTUBE_URL_REGEX, path))


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

        kind, classify_error = self._classify_path(path)
        if kind is None:
            if classify_error is not None:
                tilia.errors.display(classify_error)
            self._update_visibility(False)
            return

        # YT downloads are subject to a one-time disclaimer. Ask on the
        # main thread (here) before submitting any work to the pool —
        # building QMessageBox off-thread crashes on macOS.
        if kind == "youtube" and not acknowledge_terms_or_cancel():
            self._update_visibility(False)
            return

        # Up-front probe: for soundfile-readable audio we get exact
        # samplerate/total_frames before doing the heavy lift; for video
        # / YT we provisionally use placeholders and fill them in from
        # the worker's reported values.
        if kind == "audio":
            try:
                with soundfile.SoundFile(path) as af:
                    samplerate = af.samplerate
                    total_frames = af.frames
            except Exception:
                tilia.errors.display(tilia.errors.AUDIOWAVE_INVALID_FILE)
                self._update_visibility(False)
                return
        else:
            samplerate = 0
            total_frames = 0

        self._update_visibility(True)
        fpp = self.frames_per_peak
        if total_frames > 0:
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

        cache_key = self._cache_key(kind, path, fpp)
        if cache_key is not None:
            cached = pyramid_cache.load(cache_key)
            if cached is not None:
                self._apply_cached_pyramid(component, cached)
                return

        self._launch_peak_computation(kind, path, component, cache_key)

    @staticmethod
    def _classify_path(
        path: str,
    ) -> tuple[str | None, "tilia.errors.Error | None"]:
        """Return ``(kind, error_to_display)``.  ``kind`` is one of
        ``"audio"``, ``"video"``, ``"youtube"`` or ``None``; when None,
        the optional error is what the caller should surface to the user
        (or None for "silently hide")."""
        if _is_youtube(path):
            if not is_yt_dlp_available():
                return None, tilia.errors.YT_DLP_NOT_INSTALLED
            if not is_ffmpeg_available():
                return None, tilia.errors.FFMPEG_NOT_INSTALLED
            return "youtube", None
        # Try the cheap path first: soundfile probes the header.
        try:
            with soundfile.SoundFile(path):
                return "audio", None
        except Exception:
            pass
        # Audio extensions that soundfile rejected are corrupt — don't
        # fall back to ffmpeg for them (they aren't video).
        suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if suffix in _AUDIO_ONLY_EXTENSIONS:
            return None, tilia.errors.AUDIOWAVE_INVALID_FILE
        if is_ffmpeg_available():
            return "video", None
        return None, tilia.errors.FFMPEG_NOT_INSTALLED

    @staticmethod
    def _cache_key(kind: str, path: str, frames_per_peak: int) -> str | None:
        if kind == "youtube":
            video_id = get_video_id(path)
            if video_id is None:
                return None
            return pyramid_cache.key_for_youtube(video_id, frames_per_peak)
        try:
            return pyramid_cache.key_for_local_file(path, frames_per_peak)
        except OSError:
            return None

    def _apply_cached_pyramid(
        self, component: "Waveform", payload: pyramid_cache.PyramidPayload
    ) -> None:
        component.samplerate = payload.samplerate
        component.total_frames = payload.total_frames
        component.lod_min = list(payload.lod_min)
        component.lod_max = list(payload.lod_max)
        component.is_ready = True
        post(Post.AUDIOWAVE_PEAKS_READY, self.id, component.id)

    def _launch_peak_computation(
        self,
        kind: str,
        path: str,
        component: "Waveform",
        cache_key: str | None,
    ) -> None:
        if kind == "youtube":
            extractor = extract_peaks_via_yt_dlp
        elif kind == "video":
            extractor = extract_peaks_via_ffmpeg
        else:
            extractor = compute_peaks_sync
        cancel, signals = compute_peaks_async(
            path,
            component.frames_per_peak,
            on_done=lambda mins, maxs, sr, tf: self._on_peaks_ready(
                component, mins, maxs, sr, tf, cache_key
            ),
            on_error=lambda exc: self._on_peaks_error(exc),
            extractor=extractor,
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
        cache_key: str | None = None,
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
        if cache_key is not None:
            self._persist_to_cache(component, cache_key)

    def _persist_to_cache(self, component: "Waveform", cache_key: str) -> None:
        try:
            pyramid_cache.save(
                cache_key,
                pyramid_cache.PyramidPayload(
                    lod_min=component.lod_min,
                    lod_max=component.lod_max,
                    samplerate=component.samplerate,
                    total_frames=component.total_frames,
                    frames_per_peak=component.frames_per_peak,
                ),
            )
            cap_mb = int(
                settings.get("audiowave_timeline", "pyramid_cache_max_mb")
            )
            pyramid_cache.evict_to_cap(cap_mb * 1024 * 1024)
        except Exception:
            logger.exception("audiowave: failed to persist pyramid cache")

    def _on_peaks_error(self, exc: Exception | None = None) -> None:
        if exc is not None:
            logger.warning("audiowave peaks extraction failed: %s", exc)
        if isinstance(exc, YTUnavailableError):
            tilia.errors.display(tilia.errors.YT_VIDEO_UNAVAILABLE)
        elif isinstance(exc, YTNetworkError):
            tilia.errors.display(tilia.errors.YT_NETWORK_ERROR)
        elif isinstance(exc, YTDownloadError):
            tilia.errors.display(
                tilia.errors.YT_DLP_DOWNLOAD_FAILED, str(exc)
            )
        else:
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
        # Re-running refresh() rebuilds the waveform from the (now-known)
        # media path; it will also short-circuit through the cache when
        # we've seen this media before.
        if get(Get.MEDIA_PATH):
            self.refresh()

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
