import os
import wave
from unittest.mock import patch

import numpy as np
import pytest

import tilia.errors
from tilia import dirs
from tilia.requests import Post, listen, stop_listening
from tilia.timelines.audiowave import cache as pyramid_cache
from tilia.timelines.audiowave.peaks import CancelToken
from tilia.timelines.audiowave.timeline import AudioWaveTimeline
from tilia.timelines.audiowave.youtube import (
    YTDownloadError,
    YTNetworkError,
    YTUnavailableError,
)
from tilia.timelines.base.timeline import TimelineFlag
from tilia.timelines.component_kinds import ComponentKind


def _write_silent_wav(path, duration_sec=1.0, samplerate=44100):
    n = int(duration_sec * samplerate)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(np.zeros(n, dtype=np.int16).tobytes())


@pytest.fixture
def fresh_audiowave_tl(tls):
    """Real AudioWaveTimeline with refresh() intact (unlike the audiowave_tl
    fixture which stubs it).  Created with no media so the initial refresh is
    a no-op."""
    tl = tls.create_timeline(AudioWaveTimeline)
    return tl


class TestFlags:
    def test_flag_set_makes_timeline_read_only(self, fresh_audiowave_tl):
        flags = fresh_audiowave_tl.FLAGS
        assert TimelineFlag.NOT_CLEARABLE in flags
        assert TimelineFlag.NOT_EXPORTABLE in flags
        assert TimelineFlag.COMPONENTS_NOT_EDITABLE in flags
        assert TimelineFlag.COMPONENTS_NOT_DELETABLE in flags


class TestRefreshNoMedia:
    def test_no_media_path_hides_timeline(self, fresh_audiowave_tl, tilia_state):
        tilia_state.media_path = ""
        fresh_audiowave_tl.refresh()
        assert fresh_audiowave_tl.get_data("is_visible") is False
        assert len(fresh_audiowave_tl.components) == 0


class TestRefreshInvalidMedia:
    def test_invalid_path_displays_error_and_hides(
        self, fresh_audiowave_tl, tilia_state, tmp_path
    ):
        bogus = tmp_path / "not-an-audio-file.wav"
        bogus.write_bytes(b"not a wav")
        tilia_state.media_path = str(bogus)

        with patch.object(tilia.errors, "display") as mock_display:
            fresh_audiowave_tl.refresh()

        mock_display.assert_called_once_with(tilia.errors.AUDIOWAVE_INVALID_FILE)
        assert fresh_audiowave_tl.get_data("is_visible") is False


class TestRefreshValidMedia:
    def test_valid_audio_creates_component(
        self, fresh_audiowave_tl, tilia_state, tmp_path
    ):
        audio_path = os.fspath(tmp_path / "audio.wav")
        _write_silent_wav(audio_path, duration_sec=0.1, samplerate=44100)
        tilia_state.media_path = audio_path

        # refresh() submits async work. Capture the cancel token before it
        # tries to actually run by mocking compute_peaks_async.
        with patch(
            "tilia.timelines.audiowave.timeline.compute_peaks_async",
            return_value=(CancelToken(), object()),
        ):
            fresh_audiowave_tl.refresh()

        components = fresh_audiowave_tl.components
        assert len(components) == 1
        assert components[0].samplerate == 44100
        assert components[0].total_frames == int(0.1 * 44100)
        assert fresh_audiowave_tl.get_data("is_visible") is True


class TestCancellation:
    def test_second_refresh_cancels_first(
        self, fresh_audiowave_tl, tilia_state, tmp_path
    ):
        audio_path = os.fspath(tmp_path / "a.wav")
        _write_silent_wav(audio_path)
        tilia_state.media_path = audio_path

        captured_tokens: list[CancelToken] = []

        def fake_async(path, fpp, on_done, on_error=None, **_):
            tok = CancelToken()
            captured_tokens.append(tok)
            return tok, object()

        with patch(
            "tilia.timelines.audiowave.timeline.compute_peaks_async", fake_async
        ):
            fresh_audiowave_tl.refresh()
            fresh_audiowave_tl.refresh()

        assert len(captured_tokens) == 2
        assert captured_tokens[0].cancelled is True
        assert captured_tokens[1].cancelled is False


class TestWorkerError:
    def test_compute_error_displays_invalid_file(
        self, fresh_audiowave_tl, tilia_state, tmp_path
    ):
        audio_path = os.fspath(tmp_path / "a.wav")
        _write_silent_wav(audio_path)
        tilia_state.media_path = audio_path

        # Capture the on_error callback from compute_peaks_async, then invoke
        # it synchronously to simulate the worker raising.
        captured_on_error = []

        def fake_async(path, fpp, on_done, on_error=None, **_):
            captured_on_error.append(on_error)
            return CancelToken(), object()

        with patch(
            "tilia.timelines.audiowave.timeline.compute_peaks_async", fake_async
        ):
            fresh_audiowave_tl.refresh()

        with patch.object(tilia.errors, "display") as mock_display:
            captured_on_error[0](RuntimeError("boom"))

        mock_display.assert_called_once_with(tilia.errors.AUDIOWAVE_INVALID_FILE)
        assert fresh_audiowave_tl.get_data("is_visible") is False

    @pytest.mark.parametrize(
        "exc_factory,expected_error",
        [
            (lambda: YTUnavailableError("private"), "YT_VIDEO_UNAVAILABLE"),
            (lambda: YTNetworkError("dns"), "YT_NETWORK_ERROR"),
            (lambda: YTDownloadError("weird"), "YT_DLP_DOWNLOAD_FAILED"),
        ],
    )
    def test_typed_yt_errors_route_to_specific_user_messages(
        self,
        fresh_audiowave_tl,
        tilia_state,
        tmp_path,
        exc_factory,
        expected_error,
    ):
        audio_path = os.fspath(tmp_path / "a.wav")
        _write_silent_wav(audio_path)
        tilia_state.media_path = audio_path

        captured_on_error = []

        def fake_async(path, fpp, on_done, on_error=None, **_):
            captured_on_error.append(on_error)
            return CancelToken(), object()

        with patch(
            "tilia.timelines.audiowave.timeline.compute_peaks_async", fake_async
        ):
            fresh_audiowave_tl.refresh()

        with patch.object(tilia.errors, "display") as mock_display:
            captured_on_error[0](exc_factory())

        # First positional arg of display(error, *args) is the Error tuple.
        called_with = mock_display.call_args.args[0]
        assert called_with is getattr(tilia.errors, expected_error)
        assert fresh_audiowave_tl.get_data("is_visible") is False


class TestLegacyDeserialization:
    def test_legacy_amplitudebar_components_trigger_refresh(self, fresh_audiowave_tl):
        legacy = {
            1: {"start": 0.0, "end": 1.0, "amplitude": 0.5, "kind": "AUDIOWAVE"},
            2: {"start": 1.0, "end": 2.0, "amplitude": 0.7, "kind": "AUDIOWAVE"},
        }
        called = {"count": 0}
        original = fresh_audiowave_tl.refresh
        fresh_audiowave_tl.refresh = lambda: called.update(count=called["count"] + 1)
        try:
            fresh_audiowave_tl.deserialize_components(legacy)
        finally:
            fresh_audiowave_tl.refresh = original
        assert called["count"] == 1
        # No legacy components should have been created.
        assert len(fresh_audiowave_tl.components) == 0


class TestPyramidCache:
    @pytest.fixture
    def tmp_cache(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "pyramid_cache"
        cache_dir.mkdir()
        monkeypatch.setattr(dirs, "audiowave_pyramid_cache_path", cache_dir)
        # cache.cache_dir() now resolves to ``cache_dir / vN`` — return
        # that to the test so iterdir() lands on the actual files.
        versioned = cache_dir / f"v{pyramid_cache.SCHEMA_VERSION}"
        versioned.mkdir(exist_ok=True)
        return versioned

    def test_cache_hit_skips_worker(
        self, fresh_audiowave_tl, tilia_state, tmp_path, tmp_cache
    ):
        audio_path = os.fspath(tmp_path / "a.wav")
        _write_silent_wav(audio_path)
        tilia_state.media_path = audio_path

        # Pre-populate the cache for this exact (path, fpp).
        fpp = fresh_audiowave_tl.frames_per_peak
        key = pyramid_cache.key_for_local_file(audio_path, fpp)
        pyramid_cache.save(
            key,
            pyramid_cache.PyramidPayload(
                lod_min=[np.array([-0.3], dtype=np.float32)],
                lod_max=[np.array([0.3], dtype=np.float32)],
                samplerate=44100,
                total_frames=44100,
                frames_per_peak=fpp,
            ),
        )

        async_calls = []

        def fake_async(*args, **kwargs):
            async_calls.append((args, kwargs))
            return CancelToken(), object()

        with patch(
            "tilia.timelines.audiowave.timeline.compute_peaks_async", fake_async
        ):
            fresh_audiowave_tl.refresh()

        assert async_calls == []
        component = fresh_audiowave_tl.components[0]
        assert component.is_ready is True
        np.testing.assert_array_equal(
            component.lod_min[0], np.array([-0.3], dtype=np.float32)
        )

    def test_worker_done_persists_to_cache(
        self, fresh_audiowave_tl, tilia_state, tmp_path, tmp_cache
    ):
        audio_path = os.fspath(tmp_path / "a.wav")
        _write_silent_wav(audio_path, duration_sec=0.1)
        tilia_state.media_path = audio_path

        captured_on_done = []

        def fake_async(path, fpp, on_done, on_error=None, **_):
            captured_on_done.append(on_done)
            return CancelToken(), object()

        with patch(
            "tilia.timelines.audiowave.timeline.compute_peaks_async", fake_async
        ):
            fresh_audiowave_tl.refresh()

        captured_on_done[0](
            np.array([-0.5], dtype=np.float32),
            np.array([0.5], dtype=np.float32),
            44100,
            4410,
        )

        # The cache file should exist now.
        files = list(tmp_cache.iterdir())
        assert len(files) == 1
        assert files[0].suffix == ".npz"


class TestClassification:
    def test_youtube_path_dispatches_yt_extractor(
        self, fresh_audiowave_tl, tilia_state
    ):
        tilia_state.media_path = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        captured = []

        def fake_async(path, fpp, on_done, on_error=None, extractor=None, **_):
            captured.append(extractor)
            return CancelToken(), object()

        from tilia.settings import settings

        settings.set("audiowave_timeline", "acknowledged_yt_dlp_terms", True)
        try:
            with patch(
                "tilia.timelines.audiowave.timeline.is_yt_dlp_available",
                return_value=True,
            ), patch(
                "tilia.timelines.audiowave.timeline.is_ffmpeg_available",
                return_value=True,
            ), patch(
                "tilia.timelines.audiowave.timeline.compute_peaks_async", fake_async
            ):
                fresh_audiowave_tl.refresh()
        finally:
            settings.set("audiowave_timeline", "acknowledged_yt_dlp_terms", False)

        from tilia.timelines.audiowave.youtube import extract_peaks_via_yt_dlp

        assert captured == [extract_peaks_via_yt_dlp]

    def test_yt_disclaimer_runs_on_main_thread_before_worker_submit(
        self, fresh_audiowave_tl, tilia_state
    ):
        # Regression: previously the disclaimer was triggered inside the
        # threadpool worker, building QMessageBox off the main thread and
        # crashing on macOS. Verify acknowledge_terms_or_cancel is called
        # *before* compute_peaks_async, and that a "no" answer hides the
        # timeline without ever submitting work.
        tilia_state.media_path = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        order = []

        def fake_ack():
            order.append("ack")
            return False

        def fake_async(*a, **kw):
            order.append("async")
            return CancelToken(), object()

        with patch(
            "tilia.timelines.audiowave.timeline.is_yt_dlp_available",
            return_value=True,
        ), patch(
            "tilia.timelines.audiowave.timeline.is_ffmpeg_available",
            return_value=True,
        ), patch(
            "tilia.timelines.audiowave.timeline.acknowledge_terms_or_cancel",
            fake_ack,
        ), patch(
            "tilia.timelines.audiowave.timeline.compute_peaks_async", fake_async
        ):
            fresh_audiowave_tl.refresh()

        assert order == ["ack"]
        assert fresh_audiowave_tl.get_data("is_visible") is False

    def test_yt_url_without_yt_dlp_hides_timeline(
        self, fresh_audiowave_tl, tilia_state
    ):
        tilia_state.media_path = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        with patch(
            "tilia.timelines.audiowave.timeline.is_yt_dlp_available",
            return_value=False,
        ):
            fresh_audiowave_tl.refresh()
        assert fresh_audiowave_tl.get_data("is_visible") is False

    def test_unknown_extension_with_ffmpeg_dispatches_video_extractor(
        self, fresh_audiowave_tl, tilia_state, tmp_path
    ):
        # An mp4 file ffmpeg can't actually open will fail in the worker;
        # we only verify the dispatch chose the right extractor.
        path = tmp_path / "x.mp4"
        path.write_bytes(b"not actual mp4")
        tilia_state.media_path = str(path)

        captured = []

        def fake_async(path, fpp, on_done, on_error=None, extractor=None, **_):
            captured.append(extractor)
            return CancelToken(), object()

        with patch(
            "tilia.timelines.audiowave.timeline.is_ffmpeg_available",
            return_value=True,
        ), patch(
            "tilia.timelines.audiowave.timeline.compute_peaks_async", fake_async
        ):
            fresh_audiowave_tl.refresh()

        from tilia.timelines.audiowave.extract import extract_peaks_via_ffmpeg

        assert captured == [extract_peaks_via_ffmpeg]

    def test_audio_extension_with_corrupt_data_does_not_dispatch_video(
        self, fresh_audiowave_tl, tilia_state, tmp_path
    ):
        # A .wav that soundfile can't open shouldn't fall back to ffmpeg —
        # it's just a corrupt audio file.
        path = tmp_path / "x.wav"
        path.write_bytes(b"not a wav")
        tilia_state.media_path = str(path)

        with patch(
            "tilia.timelines.audiowave.timeline.is_ffmpeg_available",
            return_value=True,
        ), patch.object(tilia.errors, "display") as mock_display:
            fresh_audiowave_tl.refresh()

        mock_display.assert_called_once_with(tilia.errors.AUDIOWAVE_INVALID_FILE)
        assert fresh_audiowave_tl.get_data("is_visible") is False


class TestPeaksReadyEmission:
    def test_peaks_ready_post_after_compute_done(
        self, fresh_audiowave_tl, tilia_state, tmp_path
    ):
        audio_path = os.fspath(tmp_path / "a.wav")
        _write_silent_wav(audio_path, duration_sec=0.1)
        tilia_state.media_path = audio_path

        captured_on_done = []

        def fake_async(path, fpp, on_done, on_error=None, **_):
            captured_on_done.append(on_done)
            return CancelToken(), object()

        with patch(
            "tilia.timelines.audiowave.timeline.compute_peaks_async", fake_async
        ):
            fresh_audiowave_tl.refresh()

        events = []

        class Listener:
            pass

        token = Listener()
        listen(token, Post.AUDIOWAVE_PEAKS_READY, lambda *a: events.append(a))
        try:
            mins = np.array([-0.5], dtype=np.float32)
            maxs = np.array([0.5], dtype=np.float32)
            captured_on_done[0](mins, maxs, 44100, int(0.1 * 44100))
        finally:
            stop_listening(token, Post.AUDIOWAVE_PEAKS_READY)

        assert len(events) == 1
        component = fresh_audiowave_tl.components[0]
        assert component.is_ready is True
        assert events[0] == (fresh_audiowave_tl.id, component.id)
