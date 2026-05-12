"""Unit tests for `tilia.media.player.stretch`.

`render_stretched` shells out to rubberband or ffmpeg, which we can't
exercise meaningfully in CI without real binaries. The tests here
mock `shutil.which` and `subprocess.run` so we can verify the dispatch
logic (which engine is chosen, what arguments it's called with) and
the chain construction for `atempo` without depending on the host
toolchain.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tilia.media.player import stretch
from tilia.media.player.stretch import (
    StretchError,
    _chain_atempo,
    is_stretch_available,
    render_stretched,
)


class TestChainAtempo:
    @pytest.mark.parametrize("rate", [0.5, 0.75, 1.0, 1.25, 1.5, 2.0])
    def test_in_range_emits_single_filter(self, rate):
        # The 0.5..2.0 window is what `atempo` natively supports — no
        # chaining needed.
        assert _chain_atempo(rate) == f"atempo={rate}"

    def test_quarter_rate_chains_two_halves(self):
        # 0.25 = 0.5 × 0.5 — chain emits the boundary atempo=0.5 first,
        # then the remainder which is exactly 0.5 again.
        assert _chain_atempo(0.25) == "atempo=0.5,atempo=0.5"

    def test_quadruple_rate_chains_two_doubles(self):
        assert _chain_atempo(4.0) == "atempo=2.0,atempo=2.0"

    def test_eighth_rate_chains_three_halves(self):
        # 0.125 = 0.5 × 0.5 × 0.5 — far enough out of normal use that
        # we mostly care it doesn't loop forever or produce a bad chain.
        assert _chain_atempo(0.125) == "atempo=0.5,atempo=0.5,atempo=0.5"


class TestIsStretchAvailable:
    def test_true_when_rubberband_present(self):
        with patch.object(
            stretch.shutil,
            "which",
            side_effect=lambda exe: "/usr/bin/rubberband"
            if exe == "rubberband"
            else None,
        ):
            assert is_stretch_available() is True

    def test_true_when_only_ffmpeg_present(self):
        with patch.object(
            stretch.shutil,
            "which",
            side_effect=lambda exe: "/usr/bin/ffmpeg" if exe == "ffmpeg" else None,
        ):
            assert is_stretch_available() is True

    def test_false_when_neither_present(self):
        with patch.object(stretch.shutil, "which", return_value=None):
            assert is_stretch_available() is False


@pytest.fixture
def fake_source(tmp_path: Path) -> Path:
    """An on-disk file so `_cache_path` can stat() it for mtime."""
    p = tmp_path / "song.mp3"
    p.write_bytes(b"")
    return p


def _ok_subprocess() -> MagicMock:
    """Stand-in for `subprocess.run` that 'succeeds' and materialises the
    output path the command names (its last positional argument), so the
    subsequent atomic-rename in ``_run_to_partial`` has a file to publish."""

    def _run(cmd, *args, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        Path(cmd[-1]).write_bytes(b"")
        return result

    return MagicMock(side_effect=_run)


def _which_only(*available: str):
    """Returns a `shutil.which` substitute that 'finds' only the
    executables in `available`."""
    return lambda exe: f"/fake/{exe}" if exe in available else None


class TestRenderStretched:
    def test_prefers_rubberband_when_available(self, fake_source: Path, tmp_path: Path):
        # With both engines available, rubberband should be the one
        # invoked. (Recall the decode step also calls ffmpeg, so the
        # subprocess mock will see two calls.)
        run = _ok_subprocess()
        with patch.object(
            stretch.shutil, "which", _which_only("rubberband", "ffmpeg")
        ), patch.object(stretch.subprocess, "run", run), patch.object(
            stretch, "_cache_dir", return_value=tmp_path
        ):
            # _render_with_rubberband decodes via ffmpeg then runs
            # rubberband; simulate the decoded WAV existing.
            (tmp_path / "decoded.wav").write_bytes(b"")
            render_stretched(str(fake_source), 0.5)

        invoked = [call.args[0][0] for call in run.call_args_list]
        assert "rubberband" in invoked
        # ffmpeg is called as part of the decode-to-WAV step.
        assert "ffmpeg" in invoked

    def test_rubberband_uses_tempo_with_rate_value(
        self, fake_source: Path, tmp_path: Path
    ):
        # Regression: ``-T`` is rubberband's *tempo* multiplier, not the
        # *time* ratio. Passing 1/rate inverts the speed direction and
        # makes the rendered file the wrong duration, which silently
        # breaks the seek conversion in QtAudioPlayer.
        run = _ok_subprocess()
        with patch.object(
            stretch.shutil, "which", _which_only("rubberband", "ffmpeg")
        ), patch.object(stretch.subprocess, "run", run), patch.object(
            stretch, "_cache_dir", return_value=tmp_path
        ):
            render_stretched(str(fake_source), 2.0)

        rubberband_calls = [
            call for call in run.call_args_list if call.args[0][0] == "rubberband"
        ]
        assert len(rubberband_calls) == 1
        cmd = rubberband_calls[0].args[0]
        assert "--tempo" in cmd
        idx = cmd.index("--tempo")
        assert float(cmd[idx + 1]) == 2.0

    def test_falls_back_to_ffmpeg_when_no_rubberband(
        self, fake_source: Path, tmp_path: Path
    ):
        run = _ok_subprocess()
        with patch.object(stretch.shutil, "which", _which_only("ffmpeg")), patch.object(
            stretch.subprocess, "run", run
        ), patch.object(stretch, "_cache_dir", return_value=tmp_path):
            render_stretched(str(fake_source), 0.5)

        invoked = [call.args[0][0] for call in run.call_args_list]
        assert "ffmpeg" in invoked
        assert "rubberband" not in invoked

    def test_raises_when_no_engine_available(self, fake_source: Path, tmp_path: Path):
        with patch.object(stretch.shutil, "which", _which_only()), patch.object(
            stretch, "_cache_dir", return_value=tmp_path
        ):
            with pytest.raises(StretchError):
                render_stretched(str(fake_source), 0.5)

    def test_caches_existing_render(self, fake_source: Path, tmp_path: Path):
        # A cache hit should return the existing path without invoking
        # any subprocess. We materialise the expected output and check
        # subprocess.run isn't called.
        run = _ok_subprocess()
        with patch.object(stretch.shutil, "which", _which_only("ffmpeg")), patch.object(
            stretch, "_cache_dir", return_value=tmp_path
        ):
            expected = stretch._cache_path(str(fake_source), 0.5)
            expected.write_bytes(b"already rendered")

            with patch.object(stretch.subprocess, "run", run):
                result = render_stretched(str(fake_source), 0.5)

        assert result == expected
        run.assert_not_called()

    def test_rejects_nonpositive_rate(self, fake_source: Path):
        with pytest.raises(StretchError):
            render_stretched(str(fake_source), 0.0)
        with pytest.raises(StretchError):
            render_stretched(str(fake_source), -1.0)

    def test_failed_engine_raises(self, fake_source: Path, tmp_path: Path):
        failed = MagicMock(returncode=1, stderr="boom")
        with patch.object(stretch.shutil, "which", _which_only("ffmpeg")), patch.object(
            stretch.subprocess, "run", return_value=failed
        ), patch.object(stretch, "_cache_dir", return_value=tmp_path):
            with pytest.raises(StretchError, match="boom"):
                render_stretched(str(fake_source), 0.5)


class TestCacheVersion:
    """When the render pipeline changes (e.g. a bug fix in how the
    engine is invoked), bumping ``_CACHE_VERSION`` must produce a
    different cache path so old broken renders aren't silently reused."""

    def test_path_differs_across_versions(self, fake_source: Path, tmp_path: Path):
        with patch.object(stretch, "_cache_dir", return_value=tmp_path):
            with patch.object(stretch, "_CACHE_VERSION", "v1"):
                p_v1 = stretch._cache_path(str(fake_source), 0.5)
            with patch.object(stretch, "_CACHE_VERSION", "v2"):
                p_v2 = stretch._cache_path(str(fake_source), 0.5)

        assert p_v1 != p_v2, (
            "Same cache path across versions means a pipeline bug fix "
            "won't invalidate the broken renders it produced."
        )

    def test_version_change_misses_cache(self, fake_source: Path, tmp_path: Path):
        # Materialise a file at the v1 path; under v2, render_stretched
        # should NOT find it (otherwise old broken renders survive the
        # bump) and should invoke the engine to produce a fresh render.
        with patch.object(stretch, "_cache_dir", return_value=tmp_path):
            with patch.object(stretch, "_CACHE_VERSION", "v1"):
                v1_path = stretch._cache_path(str(fake_source), 0.5)
            v1_path.write_bytes(b"old broken render")

            run = _ok_subprocess()
            with patch.object(
                stretch.shutil, "which", _which_only("ffmpeg")
            ), patch.object(stretch.subprocess, "run", run), patch.object(
                stretch, "_CACHE_VERSION", "v2"
            ):
                render_stretched(str(fake_source), 0.5)

        # Engine was invoked, meaning the v1 leftover did not satisfy
        # the v2 lookup.
        assert run.called


class TestCachePrune:
    """``_prune_cache_to_limit`` is the only mechanism that reclaims
    disk after a long session of opening different files at different
    rates. It must evict by mtime (oldest first) and stop when total
    size falls under the limit."""

    def test_under_limit_is_a_noop(self, tmp_path: Path):
        a = tmp_path / "a.wav"
        b = tmp_path / "b.wav"
        a.write_bytes(b"x" * 100)
        b.write_bytes(b"x" * 100)

        with patch.object(stretch, "_cache_dir", return_value=tmp_path), patch.object(
            stretch, "_CACHE_MAX_BYTES", 10_000
        ):
            stretch._prune_cache_to_limit()

        assert a.exists()
        assert b.exists()

    def test_evicts_oldest_first(self, tmp_path: Path):
        # Three files, ranked by mtime. Limit forces eviction of the
        # oldest until total drops under the cap.
        import os
        import time

        old = tmp_path / "old.wav"
        mid = tmp_path / "mid.wav"
        new = tmp_path / "new.wav"
        for p in (old, mid, new):
            p.write_bytes(b"x" * 100)
        now = time.time()
        os.utime(old, (now - 300, now - 300))
        os.utime(mid, (now - 200, now - 200))
        os.utime(new, (now - 100, now - 100))

        # Cap at 150 bytes — must evict two of the three.
        with patch.object(stretch, "_cache_dir", return_value=tmp_path), patch.object(
            stretch, "_CACHE_MAX_BYTES", 150
        ):
            stretch._prune_cache_to_limit()

        assert not old.exists(), "Oldest should have been evicted first."
        assert not mid.exists(), "Mid should have been evicted second."
        assert new.exists(), "Newest should have been kept."

    def test_runs_after_successful_render(self, fake_source: Path, tmp_path: Path):
        # _prune_cache_to_limit is wired into render_stretched so long
        # sessions don't accumulate orphaned files. We can't easily
        # observe the prune from outside, but we can confirm it's called.
        run = _ok_subprocess()
        with patch.object(stretch.shutil, "which", _which_only("ffmpeg")), patch.object(
            stretch.subprocess, "run", run
        ), patch.object(stretch, "_cache_dir", return_value=tmp_path), patch.object(
            stretch, "_prune_cache_to_limit"
        ) as prune:
            render_stretched(str(fake_source), 0.5)

        prune.assert_called_once()

    def test_prune_sweeps_stale_partial_files(self, tmp_path: Path):
        # An interrupted render leaves a `.partial` sibling that never
        # satisfies a cache lookup but still occupies disk. Prune is the
        # janitor for these; without this sweep they'd linger until
        # the next successful render of the *same* (src, rate) cleans
        # them, which may never happen for a one-off rate the user tried.
        stale = tmp_path / "deadbeefcafe1234.wav.partial"
        stale.write_bytes(b"interrupted render bytes")

        with patch.object(stretch, "_cache_dir", return_value=tmp_path):
            stretch._prune_cache_to_limit()

        assert not stale.exists()


class TestPartialRenderAtomicRename:
    """Renders must be atomic: an interrupted subprocess must NOT leave a
    file at the final cache path. The cache lookup is just `dst.exists()`,
    so a partial file there would be returned forever as a 'hit' — exactly
    the bug that wedged playback at certain rates after a killed render."""

    def test_failed_render_does_not_publish_final_path(
        self, fake_source: Path, tmp_path: Path
    ):
        # The engine fails. We must NOT see a file at the cache path
        # afterwards; otherwise the next call would treat the failed
        # output as a cache hit.
        failed = MagicMock(returncode=1, stderr="boom")
        dst = None
        with patch.object(stretch, "_cache_dir", return_value=tmp_path), patch.object(
            stretch.shutil, "which", _which_only("ffmpeg")
        ), patch.object(stretch.subprocess, "run", return_value=failed):
            dst = stretch._cache_path(str(fake_source), 0.5)
            with pytest.raises(StretchError):
                render_stretched(str(fake_source), 0.5)

        assert dst is not None
        assert not dst.exists(), (
            "Failed render published a file at the cache path; next lookup "
            "would return it as a stale cache hit."
        )
        assert not stretch._partial_path(dst).exists(), (
            "Failed render left a `.partial` sibling — it should be cleaned "
            "up on failure to avoid disk leaks."
        )

    def test_killed_subprocess_does_not_publish_final_path(
        self, fake_source: Path, tmp_path: Path
    ):
        # Simulate `subprocess.run` being interrupted (BaseException
        # like KeyboardInterrupt or process kill). The partial must be
        # removed and the final path must remain absent so the cache
        # doesn't memorise the interrupted state.
        with patch.object(stretch, "_cache_dir", return_value=tmp_path), patch.object(
            stretch.shutil, "which", _which_only("ffmpeg")
        ), patch.object(stretch.subprocess, "run", side_effect=KeyboardInterrupt):
            dst = stretch._cache_path(str(fake_source), 0.5)
            with pytest.raises(KeyboardInterrupt):
                render_stretched(str(fake_source), 0.5)

        assert not dst.exists()
        assert not stretch._partial_path(dst).exists()

    def test_preexisting_partial_does_not_satisfy_cache(
        self, fake_source: Path, tmp_path: Path
    ):
        # The classic poisoned-cache shape: a `.partial` survives from a
        # killed run. Cache lookup checks the final name only, so this
        # must be a miss and trigger a fresh render. Crucially, the
        # final path created by the new render is the *atomically renamed*
        # one — not just a copy of the partial.
        run = _ok_subprocess()
        with patch.object(stretch, "_cache_dir", return_value=tmp_path):
            dst = stretch._cache_path(str(fake_source), 0.5)
            stretch._partial_path(dst).write_bytes(b"stale partial from killed run")

            with patch.object(
                stretch.shutil, "which", _which_only("ffmpeg")
            ), patch.object(stretch.subprocess, "run", run):
                result = render_stretched(str(fake_source), 0.5)

        assert run.called, "A stale partial should NOT satisfy the cache."
        assert result == dst
        assert dst.exists()

    def test_successful_render_leaves_no_partial(
        self, fake_source: Path, tmp_path: Path
    ):
        run = _ok_subprocess()
        with patch.object(stretch.shutil, "which", _which_only("ffmpeg")), patch.object(
            stretch.subprocess, "run", run
        ), patch.object(stretch, "_cache_dir", return_value=tmp_path):
            dst = render_stretched(str(fake_source), 0.5)

        assert dst.exists()
        assert not stretch._partial_path(
            dst
        ).exists(), "Atomic rename should consume the .partial, not leave a sibling."
