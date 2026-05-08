import os

import numpy as np
import pytest

from tilia import dirs
from tilia.timelines.audiowave import cache


@pytest.fixture
def tmp_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dirs, "audiowave_pyramid_cache_path", tmp_path)
    versioned = tmp_path / f"v{cache.SCHEMA_VERSION}"
    versioned.mkdir(exist_ok=True)
    return versioned


def _payload(samplerate=44100, total_frames=4410, fpp=128):
    return cache.PyramidPayload(
        lod_min=[
            np.array([-0.5, -0.4], dtype=np.float32),
            np.array([-0.5], dtype=np.float32),
        ],
        lod_max=[
            np.array([0.5, 0.4], dtype=np.float32),
            np.array([0.5], dtype=np.float32),
        ],
        samplerate=samplerate,
        total_frames=total_frames,
        frames_per_peak=fpp,
    )


class TestRoundTrip:
    def test_save_then_load_returns_equivalent_payload(self, tmp_cache_dir):
        original = _payload()
        cache.save("abc123", original)
        loaded = cache.load("abc123")
        assert loaded is not None
        assert loaded.samplerate == original.samplerate
        assert loaded.total_frames == original.total_frames
        assert loaded.frames_per_peak == original.frames_per_peak
        assert len(loaded.lod_min) == len(original.lod_min)
        for a, b in zip(loaded.lod_min, original.lod_min):
            np.testing.assert_array_equal(a, b)
        for a, b in zip(loaded.lod_max, original.lod_max):
            np.testing.assert_array_equal(a, b)

    def test_load_missing_returns_none(self, tmp_cache_dir):
        assert cache.load("missing-key") is None


class TestKeyStability:
    def test_same_inputs_yield_same_key(self, tmp_path):
        f = tmp_path / "audio.wav"
        f.write_bytes(b"x")
        k1 = cache.key_for_local_file(f, 128)
        k2 = cache.key_for_local_file(f, 128)
        assert k1 == k2

    def test_frames_per_peak_changes_key(self, tmp_path):
        f = tmp_path / "audio.wav"
        f.write_bytes(b"x")
        assert cache.key_for_local_file(f, 128) != cache.key_for_local_file(f, 256)

    def test_mtime_changes_key(self, tmp_path):
        f = tmp_path / "audio.wav"
        f.write_bytes(b"x")
        k1 = cache.key_for_local_file(f, 128)
        # Force a different mtime.
        os.utime(f, (1, 1))
        k2 = cache.key_for_local_file(f, 128)
        assert k1 != k2

    def test_youtube_key_differs_per_video(self, tmp_path):
        assert cache.key_for_youtube("aaa", 128) != cache.key_for_youtube("bbb", 128)
        assert cache.key_for_youtube("aaa", 128) != cache.key_for_youtube("aaa", 256)


class TestAtomicWrite:
    def test_no_stale_temp_file_remains_after_save(self, tmp_cache_dir):
        cache.save("k", _payload())
        files = list(tmp_cache_dir.iterdir())
        # Exactly one file: the final .npz, no leftover .tmp / partial.
        assert len(files) == 1
        assert files[0].name == "k.npz"


class TestEviction:
    def test_evict_to_cap_drops_oldest_first(self, tmp_cache_dir):
        # Three small entries, then evict to a cap that fits two.
        cache.save("oldest", _payload())
        cache.save("middle", _payload())
        cache.save("newest", _payload())

        # Force monotonic mtimes (filesystems with second-resolution mtimes
        # would tie all three).
        now = os.path.getmtime(tmp_cache_dir / "newest.npz")
        os.utime(tmp_cache_dir / "oldest.npz", (now - 200, now - 200))
        os.utime(tmp_cache_dir / "middle.npz", (now - 100, now - 100))
        os.utime(tmp_cache_dir / "newest.npz", (now, now))

        sizes = sum(f.stat().st_size for f in tmp_cache_dir.glob("*.npz"))
        cap = sizes - (tmp_cache_dir / "oldest.npz").stat().st_size

        cache.evict_to_cap(cap)

        remaining = {f.name for f in tmp_cache_dir.glob("*.npz")}
        assert "oldest.npz" not in remaining
        assert "middle.npz" in remaining
        assert "newest.npz" in remaining

    def test_evict_no_op_when_under_cap(self, tmp_cache_dir):
        cache.save("k", _payload())
        cache.evict_to_cap(10**9)  # 1 GB
        assert (tmp_cache_dir / "k.npz").exists()


class TestEvictionThrottle:
    @pytest.fixture(autouse=True)
    def _reset_throttle(self):
        cache.reset_eviction_throttle()
        yield
        cache.reset_eviction_throttle()

    def test_small_save_within_threshold_skips_scan(self, monkeypatch):
        # A single small save with a generous cap should not scan.
        scans = {"count": 0}
        monkeypatch.setattr(
            cache, "evict_to_cap", lambda *_: scans.update(count=scans["count"] + 1)
        )
        cache.maybe_evict_to_cap(100 * 1024 * 1024, payload_size_hint=1024)
        assert scans["count"] == 0

    def test_size_overshoot_triggers_scan(self, monkeypatch):
        scans = {"count": 0}
        monkeypatch.setattr(
            cache, "evict_to_cap", lambda *_: scans.update(count=scans["count"] + 1)
        )
        cap = 100 * 1024 * 1024  # 100 MB cap
        # 30 MB > 25% of 100 MB → fire on first save.
        cache.maybe_evict_to_cap(cap, payload_size_hint=30 * 1024 * 1024)
        assert scans["count"] == 1

    def test_save_count_interval_triggers_scan(self, monkeypatch):
        scans = {"count": 0}
        monkeypatch.setattr(
            cache, "evict_to_cap", lambda *_: scans.update(count=scans["count"] + 1)
        )
        cap = 100 * 1024 * 1024
        for _ in range(50):  # _EVICTION_SAVE_INTERVAL
            cache.maybe_evict_to_cap(cap, payload_size_hint=0)
        assert scans["count"] == 1

    def test_throttle_resets_after_scan(self, monkeypatch):
        # After a scan fires, the next small save should NOT scan again.
        scans = {"count": 0}
        monkeypatch.setattr(
            cache, "evict_to_cap", lambda *_: scans.update(count=scans["count"] + 1)
        )
        cap = 100 * 1024 * 1024
        cache.maybe_evict_to_cap(cap, payload_size_hint=30 * 1024 * 1024)
        assert scans["count"] == 1
        cache.maybe_evict_to_cap(cap, payload_size_hint=1024)
        assert scans["count"] == 1


class TestCorruption:
    def test_corrupt_file_returns_none_and_removes(self, tmp_cache_dir):
        bad = tmp_cache_dir / "bad.npz"
        bad.write_bytes(b"not a valid npz")
        assert cache.load("bad") is None
        # File removed so we won't keep tripping over it.
        assert not bad.exists()
