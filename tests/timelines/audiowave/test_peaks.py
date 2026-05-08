import os
import wave

import numpy as np
import pytest

from tilia.timelines.audiowave.peaks import (
    adapt_frames_per_peak,
    build_lod_pyramid,
    compute_peaks_sync,
    estimate_pyramid_bytes,
)


def _write_test_wav(path: str, samples: np.ndarray, samplerate: int = 44100):
    samples = np.asarray(samples, dtype=np.float32)
    samples = np.clip(samples, -1.0, 1.0)
    int_samples = (samples * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(int_samples.tobytes())


class TestComputePeaksSync:
    def test_constant_signal(self, tmp_path):
        path = os.fspath(tmp_path / "constant.wav")
        # Two-bucket signal: first half +0.5, second half -0.5.
        samples = np.concatenate(
            [np.full(1024, 0.5, dtype=np.float32),
             np.full(1024, -0.5, dtype=np.float32)]
        )
        _write_test_wav(path, samples, samplerate=44100)

        mins, maxs, sr, total = compute_peaks_sync(path, frames_per_peak=1024)

        assert sr == 44100
        assert total == 2048
        assert mins.shape == (2,)
        assert maxs.shape == (2,)
        # Normalized so max(abs) == 1.0
        assert maxs[0] == pytest.approx(1.0, abs=1e-3)
        assert mins[0] == pytest.approx(1.0, abs=1e-3)
        assert mins[1] == pytest.approx(-1.0, abs=1e-3)
        assert maxs[1] == pytest.approx(-1.0, abs=1e-3)

    def test_returns_float32(self, tmp_path):
        path = os.fspath(tmp_path / "f.wav")
        _write_test_wav(path, np.zeros(2048, dtype=np.float32))
        mins, maxs, _, _ = compute_peaks_sync(path, frames_per_peak=1024)
        assert mins.dtype == np.float32
        assert maxs.dtype == np.float32


class TestBuildLodPyramid:
    def test_halves_each_level(self):
        mins = np.array([-0.1, -0.2, -0.3, -0.4, -0.5, -0.6, -0.7, -0.8],
                        dtype=np.float32)
        maxs = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
                        dtype=np.float32)
        lod_min, lod_max = build_lod_pyramid(mins, maxs)
        assert len(lod_min) == 4  # 8 -> 4 -> 2 -> 1
        assert lod_min[0].shape == (8,)
        assert lod_min[1].shape == (4,)
        assert lod_min[2].shape == (2,)
        assert lod_min[3].shape == (1,)

    def test_correctness_min_max_pairing(self):
        mins = np.array([-0.1, -0.5, -0.2, -0.3], dtype=np.float32)
        maxs = np.array([0.1, 0.5, 0.2, 0.3], dtype=np.float32)
        lod_min, lod_max = build_lod_pyramid(mins, maxs)
        np.testing.assert_allclose(lod_min[1], [-0.5, -0.3])
        np.testing.assert_allclose(lod_max[1], [0.5, 0.3])


class TestReduceatBoundary:
    """Regression: at certain zoom levels the per-pixel min/max aggregation
    used to build a reduceat index equal to ``len(lod_array)``, which numpy
    rejects with IndexError and which left QPainter in a corrupted state
    (subsequent paints could segfault).  Verify that reduceat tolerates
    every index produced by clipping into ``[0, n - 1]``.
    """

    def test_indices_at_array_length_are_safe(self):
        # A small LOD array; we explicitly construct indices that include
        # the maximum legal value (n - 1).
        a = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        idx = np.array([0, 2, 4, 4, 4], dtype=np.int64)
        # Should not raise.
        result = np.minimum.reduceat(a, idx)
        assert result.shape == (5,)


class TestLegacyTlaFormat:
    def test_legacy_amplitude_components_trigger_refresh(self, audiowave_tl):
        legacy = {
            1: {"start": 0.0, "end": 1.0, "amplitude": 0.5, "kind": "AUDIOWAVE"},
            2: {"start": 1.0, "end": 2.0, "amplitude": 0.7, "kind": "AUDIOWAVE"},
        }
        called = {"count": 0}

        original_refresh = audiowave_tl.refresh

        def tracking_refresh():
            called["count"] += 1

        audiowave_tl.refresh = tracking_refresh
        try:
            audiowave_tl.deserialize_components(legacy)
        finally:
            audiowave_tl.refresh = original_refresh

        assert called["count"] == 1


class TestLodPyramidInvariant:
    """Each pyramid level must be a faithful min-of-mins / max-of-maxes
    aggregation of the level below."""

    def test_random_signal_satisfies_invariant(self):
        rng = np.random.default_rng(seed=42)
        n = 1024
        mins = rng.uniform(-1.0, 0.0, size=n).astype(np.float32)
        maxs = rng.uniform(0.0, 1.0, size=n).astype(np.float32)

        lod_min, lod_max = build_lod_pyramid(mins, maxs)

        for k in range(len(lod_min) - 1):
            child_min = lod_min[k]
            child_max = lod_max[k]
            parent_min = lod_min[k + 1]
            parent_max = lod_max[k + 1]
            n_pairs = len(parent_min)
            for i in range(n_pairs):
                expected_min = min(child_min[2 * i], child_min[2 * i + 1])
                expected_max = max(child_max[2 * i], child_max[2 * i + 1])
                assert parent_min[i] == pytest.approx(expected_min)
                assert parent_max[i] == pytest.approx(expected_max)


class TestComputePeaksEdges:
    def test_total_frames_not_divisible_by_frames_per_peak(self, tmp_path):
        # 2050 frames at fpp=1024 → 2 buckets, last 2 frames discarded.
        path = os.fspath(tmp_path / "odd.wav")
        samples = np.full(2050, 0.5, dtype=np.float32)
        _write_test_wav(path, samples, samplerate=44100)
        mins, maxs, _, total = compute_peaks_sync(path, frames_per_peak=1024)
        assert total == 2050
        assert mins.shape == (2,)
        assert maxs.shape == (2,)

    def test_silent_signal_produces_zero_peaks(self, tmp_path):
        path = os.fspath(tmp_path / "silent.wav")
        _write_test_wav(path, np.zeros(2048, dtype=np.float32))
        mins, maxs, _, _ = compute_peaks_sync(path, frames_per_peak=1024)
        # Normalization of all-zeros doesn't blow up; values stay at 0.
        np.testing.assert_array_equal(mins, np.zeros(2, dtype=np.float32))
        np.testing.assert_array_equal(maxs, np.zeros(2, dtype=np.float32))

    def test_sine_envelope_reaches_unit_amplitude(self, tmp_path):
        # 1 kHz sine at 44.1 kHz, 0.5 seconds.  After normalization the
        # level-0 envelope should hit ±1.0 in every bucket.
        path = os.fspath(tmp_path / "sine.wav")
        sr = 44100
        n = sr // 2
        t = np.arange(n) / sr
        samples = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
        _write_test_wav(path, samples, samplerate=sr)
        mins, maxs, _, _ = compute_peaks_sync(path, frames_per_peak=512)
        # Each bucket holds ≥11 cycles, so it must contain a near-peak in both directions.
        assert np.all(maxs > 0.95)
        assert np.all(mins < -0.95)


class TestPyramidMemoryBound:
    """The LOD pyramid is roughly 16 * total_frames / fpp bytes (factor 16 =
    2 arrays * 4 bytes/float32 * geometric series sum 2 across all levels).
    Cap memory by bumping fpp to powers of two until it fits."""

    def test_short_file_uses_user_fpp(self):
        # 30 s @ 44.1 kHz mono ≈ 1.3M frames * 16 / 128 = ~165 KB. Fits easily.
        total_frames = 30 * 44100
        assert adapt_frames_per_peak(total_frames, 128) == 128

    def test_huge_file_bumps_to_power_of_two(self):
        # 4 hours @ 44.1 kHz = ~635M frames; at fpp=128 → ~80 MB (fits).
        # Force a tight budget to exercise the bumping logic.
        total_frames = 4 * 3600 * 44100
        bumped = adapt_frames_per_peak(total_frames, 128, budget_bytes=10 * 1024 * 1024)
        assert bumped > 128
        assert bumped & (bumped - 1) == 0  # power of two
        assert estimate_pyramid_bytes(total_frames, bumped) <= 10 * 1024 * 1024

    def test_budget_at_default_keeps_one_hour_at_default_fpp(self):
        # Sanity check: at default frames_per_peak=128 and budget=100 MB,
        # a 1-hour 44.1 kHz file should not get bumped.
        total_frames = 3600 * 44100
        assert adapt_frames_per_peak(total_frames, 128) == 128


class TestCancellation:
    def test_cancel_during_compute_returns_partial(self, tmp_path):
        path = os.fspath(tmp_path / "long.wav")
        # 16k frames / 1024 fpp = 16 buckets — enough to cancel midway.
        _write_test_wav(path, np.zeros(16384, dtype=np.float32))
        token = compute_peaks_sync.__globals__["CancelToken"]()
        token.cancelled = True
        mins, maxs, _, _ = compute_peaks_sync(path, frames_per_peak=1024, cancel=token)
        # When cancelled before the loop, the buckets stay at zero.
        np.testing.assert_array_equal(mins, np.zeros_like(mins))
        np.testing.assert_array_equal(maxs, np.zeros_like(maxs))
