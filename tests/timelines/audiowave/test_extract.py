import os
import shutil
import wave
from unittest.mock import patch

import numpy as np
import pytest

from tilia.timelines.audiowave import extract
from tilia.timelines.audiowave.peaks import CancelToken


HAS_FFMPEG = shutil.which("ffmpeg") is not None
ffmpeg_required = pytest.mark.skipif(
    not HAS_FFMPEG, reason="ffmpeg not installed on test runner"
)


def _write_pcm_wav(path, samples_int16, samplerate=44100):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(samples_int16.astype(np.int16).tobytes())


class TestAvailability:
    def test_returns_bool(self):
        assert isinstance(extract.is_ffmpeg_available(), bool)

    def test_missing_when_not_in_path(self):
        with patch("tilia.timelines.audiowave.extract.shutil.which", return_value=None):
            assert extract.is_ffmpeg_available() is False


@ffmpeg_required
class TestStreamingExtraction:
    """Round-trip tests against a real ffmpeg binary, on a tiny WAV.

    ffmpeg can read WAV directly, so we can drive the streaming pipeline
    without needing a video fixture in the repo.
    """

    def test_silent_audio_yields_zero_peaks(self, tmp_path):
        path = os.fspath(tmp_path / "silent.wav")
        _write_pcm_wav(path, np.zeros(4410, dtype=np.int16))

        mins, maxs, sr, total = extract.extract_peaks_via_ffmpeg(path, 128)

        assert sr == extract.TARGET_SAMPLERATE
        assert total > 0
        assert np.all(mins == 0)
        assert np.all(maxs == 0)

    def test_loud_signal_normalizes_to_unit_amplitude(self, tmp_path):
        path = os.fspath(tmp_path / "loud.wav")
        # Square wave at int16 max so peaks should normalize close to ±1.
        n = 4410
        sig = np.where(np.arange(n) % 2 == 0, 30000, -30000).astype(np.int16)
        _write_pcm_wav(path, sig)

        mins, maxs, _, _ = extract.extract_peaks_via_ffmpeg(path, 128)
        assert mins.size > 0
        assert maxs.max() == pytest.approx(1.0, abs=0.05)
        assert mins.min() == pytest.approx(-1.0, abs=0.05)

    def test_cancellation_terminates_early(self, tmp_path):
        path = os.fspath(tmp_path / "long.wav")
        # 5 seconds of audio — enough that early cancel should produce
        # noticeably fewer peaks than full extraction.
        _write_pcm_wav(
            path, np.zeros(5 * 44100, dtype=np.int16)
        )
        cancel = CancelToken()
        cancel.cancelled = True
        mins, _, _, total = extract.extract_peaks_via_ffmpeg(path, 128, cancel)
        # With cancel pre-set, the loop should bail before reading anything.
        assert total == 0
        assert mins.size == 0

    def test_invalid_path_raises(self, tmp_path):
        with pytest.raises(RuntimeError):
            extract.extract_peaks_via_ffmpeg(
                str(tmp_path / "nope.wav"), 128
            )
