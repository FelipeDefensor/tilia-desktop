"""Pitch-preserving time-stretch rendering for local audio playback.

Used by `QtAudioPlayer` to render a stretched WAV when the user changes
playback rate to something other than 1.0×. The original `QMediaPlayer`
backend ships native rate control, but it warps pitch (it just plays
samples faster / slower). Music-transcription users want the *opposite*:
keep pitch, change duration.

Two engines are tried in order:

1. **rubberband** (preferred). Highest-quality time-stretch, especially
   at the slow rates (0.25–0.5×) that matter most for transcription —
   it has separate handling for percussive and harmonic content and
   does not smear transients the way phase-vocoder approaches do. The
   CLI tool needs WAV input, so non-WAV sources are first decoded via
   ffmpeg.

2. **ffmpeg ``atempo`` filter** (fallback). Always available wherever
   ffmpeg is — and TiLiA already depends on ffmpeg for audiowave
   rendering, so this fallback adds no install footprint. ``atempo``
   accepts only the 0.5–2.0× range per filter instance; for rates
   outside that we chain it (``atempo=0.5,atempo=0.5`` for 0.25×).

The rendered files live in a per-process temp directory and are cached
by ``(source_path, source_mtime, rate)`` so successive switches to the
same rate are instant after the first render.
"""

from __future__ import annotations

import hashlib
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path


class StretchError(RuntimeError):
    """Raised when neither rubberband nor ffmpeg are available, or when
    the chosen engine exits with a non-zero status. Callers should treat
    this as 'falling back to Qt's native (pitch-warping) rate change is
    fine' — it is much better than refusing to play at all."""


# Bump when the render command, output format, or anything else that
# would invalidate previously-cached files changes. The bump is folded
# into the cache key hash so old files become unreachable (and the LRU
# prune below reclaims their disk space over time).
#
# v1 -> v2: fixed rubberband direction (was -T 1/rate, now --tempo rate).
_CACHE_VERSION = "v2"

# Soft cap on total cache size on disk. Each rendered file is the full
# audio re-encoded as WAV, so a single song at multiple rates can easily
# reach 100s of MB. 2 GB is enough to hold dozens of files for a typical
# transcription session without filling the user's temp partition.
_CACHE_MAX_BYTES = 2 * 1024**3


def is_stretch_available() -> bool:
    """True iff at least one supported engine is on PATH."""
    return shutil.which("rubberband") is not None or shutil.which("ffmpeg") is not None


def _cache_dir() -> Path:
    """Stable per-process temp directory under the OS temp root. Not
    cleaned up automatically — `QtAudioPlayer` deletes its cached files
    on unload / exit."""
    base = Path(tempfile.gettempdir()) / "tilia-stretch-cache"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cache_path(src: str, rate: float) -> Path:
    """Hash of cache version + source path + mtime + rate. Including
    mtime invalidates the cache if the user edits the source file in
    place; including the version invalidates everything when the render
    pipeline changes (see ``_CACHE_VERSION``)."""
    src_path = Path(src)
    mtime = src_path.stat().st_mtime if src_path.exists() else 0
    key = f"{_CACHE_VERSION}|{src}|{mtime}|{rate}".encode("utf-8")
    digest = hashlib.sha1(key).hexdigest()[:16]
    return _cache_dir() / f"{digest}.wav"


def _prune_cache_to_limit() -> None:
    """Evict oldest .wav files in the cache dir until total size is
    under ``_CACHE_MAX_BYTES``. Called after each successful render so
    long sessions or many opened files don't fill the disk indefinitely.

    Eviction order is oldest-mtime-first: a render that was used recently
    will have a fresher mtime than one that hasn't been touched (the OS
    bumps atime on read but atime isn't reliable cross-platform, so we
    use mtime as a coarse proxy).

    Also sweeps stale ``.partial`` files left by a render that was killed
    mid-flight. These never satisfy a cache lookup (the atomic-rename in
    ``_run_to_partial`` only publishes the final name on success), but
    they still occupy disk until cleaned."""
    cache = _cache_dir()
    for p in cache.glob("*.partial.wav"):
        try:
            p.unlink()
        except OSError:
            pass
    entries: list[tuple[Path, int, float]] = []
    total = 0
    for p in cache.glob("*.wav"):
        # Partials were already swept above; the LRU loop should only
        # see real cache entries.
        if ".partial." in p.name:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        entries.append((p, st.st_size, st.st_mtime))
        total += st.st_size
    if total <= _CACHE_MAX_BYTES:
        return
    entries.sort(key=lambda t: t[2])  # oldest first
    for path, size, _mtime in entries:
        if total <= _CACHE_MAX_BYTES:
            return
        try:
            path.unlink()
            total -= size
        except OSError:
            # Skip files held open by another process; the next prune
            # pass will get them.
            pass


def _chain_atempo(rate: float) -> str:
    """Build an ``atempo`` filter chain that achieves ``rate``.

    Single ``atempo`` only supports 0.5–2.0×. Outside that range we
    multiply by 0.5 or 2.0 repeatedly and finish with a final factor
    that lands in-range. For typical music-transcription rates
    (0.25–2.0×) at most two filters get chained.
    """
    if 0.5 <= rate <= 2.0:
        return f"atempo={rate}"

    parts: list[str] = []
    r = rate
    while r > 2.0:
        parts.append("atempo=2.0")
        r /= 2.0
    while r < 0.5:
        parts.append("atempo=0.5")
        r *= 2.0
    parts.append(f"atempo={r}")
    return ",".join(parts)


def _make_partial_path(dst: Path) -> Path:
    """Return a fresh, unique scratch-output path beside ``dst``.

    Each call generates a different name. This matters when multiple
    threads concurrently target the same final ``dst`` — which happens
    routinely in practice:

    * All four preemptive rate renders decode the source to the same
      WAV first, so their decode-step partials collide on a single
      deterministic name.
    * A rapid reload (e.g. opening a .tla that triggers an audiowave
      timeline + the player's preemptive renders for the same source)
      restarts work for keys that are still in flight.

    With a deterministic partial name, the second attempt's defensive
    ``unlink(missing_ok=True)`` crashes on Windows with PermissionError
    because the first attempt's subprocess holds an exclusive write
    lock on that exact path. A unique name keeps each attempt out of
    every other's way; leftovers are reaped by ``_prune_cache_to_limit``.

    Trailing ``.partial.wav`` is preserved so:
    * the cache-sweep glob ``*.partial.wav`` still matches, and
    * ffmpeg / rubberband (via libsndfile) still pick the WAV muxer
      from the extension. An earlier version that put ``.partial`` as
      the trailing suffix made ffmpeg fail with "Unable to choose an
      output format".
    """
    unique = secrets.token_hex(4)
    return dst.parent / f"{dst.stem}-{unique}.partial{dst.suffix}"


def _run_to_partial(cmd: list[str], dst: Path, what: str, src_for_error: str) -> None:
    """Run ``cmd`` writing to a unique ``.partial`` sibling of ``dst``, then
    atomic-rename onto ``dst``. If the subprocess fails or is killed, the
    partial is removed and ``dst`` is never created. This is what prevents
    an interrupted render from poisoning the cache: the cache lookup only
    sees fully-written files.
    """
    tmp = _make_partial_path(dst)
    cmd = list(cmd)
    cmd[-1] = str(tmp)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if result.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise StretchError(
            f"{what} failed for {src_for_error!r}: {result.stderr.strip()}"
        )
    # Publish to dst. If a concurrent attempt already wrote dst (and a
    # downstream consumer like rubberband may have it open for reading),
    # Windows refuses the rename with a sharing violation. Treat that as
    # "another thread won the race" — our partial is redundant content,
    # discard it. The decoded-WAV destination is shared by every rate's
    # rubberband path, so this race is regular, not exceptional.
    try:
        tmp.replace(dst)
    except OSError:
        if dst.exists():
            tmp.unlink(missing_ok=True)
        else:
            raise


def _decode_to_wav(src: str) -> Path:
    """Decode ``src`` to a temporary WAV in the cache directory. Used by
    the rubberband path because the CLI tool only reads libsndfile
    formats (WAV / FLAC / AIFF / OGG — not MP3 / M4A)."""
    if not shutil.which("ffmpeg"):
        raise StretchError(
            "Cannot decode source for rubberband: ffmpeg is not available."
        )
    dst = _cache_dir() / (
        hashlib.sha1(f"decode|{src}".encode("utf-8")).hexdigest()[:16] + ".wav"
    )
    if dst.exists():
        return dst
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-i",
        src,
        "-vn",
        str(dst),
    ]
    _run_to_partial(cmd, dst, "ffmpeg decode", src)
    return dst


def _render_with_rubberband(src: str, rate: float, dst: Path) -> None:
    # rubberband's ``--tempo`` (``-T``) is the *tempo multiplier* — pass
    # the playback rate directly. ``rate=2.0`` → twice as fast (output
    # half as long); ``rate=0.5`` → half speed (output twice as long).
    # (Don't confuse ``-T`` with ``-t / --time``, which is the inverse
    # *time ratio*. Mixing them up inverts the speed direction and
    # silently breaks the seek-time math, since seek targets a position
    # in the *stretched-file* timeline.)
    src_wav = _decode_to_wav(src)
    cmd = [
        "rubberband",
        "-q",  # quiet
        "--tempo",
        f"{rate}",
        str(src_wav),
        str(dst),
    ]
    _run_to_partial(cmd, dst, "rubberband", src)


def _render_with_ffmpeg(src: str, rate: float, dst: Path) -> None:
    atempo = _chain_atempo(rate)
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-i",
        src,
        "-vn",
        "-filter:a",
        atempo,
        str(dst),
    ]
    _run_to_partial(cmd, dst, "ffmpeg atempo", src)


def render_stretched(src: str, rate: float) -> Path:
    """Produce a pitch-preserved time-stretched WAV of ``src`` at ``rate``.

    Returns a cached path if a render with the same source mtime and
    rate already exists. Raises ``StretchError`` when no engine is
    available, or when the chosen engine fails.

    Note: caller is responsible for the temp file's lifetime. The
    convention used by ``QtAudioPlayer`` is to clear the cache on
    media unload / exit.
    """
    if rate <= 0:
        raise StretchError(f"Playback rate must be positive (got {rate}).")

    dst = _cache_path(src, rate)
    if dst.exists():
        return dst

    if shutil.which("rubberband"):
        _render_with_rubberband(src, rate, dst)
    elif shutil.which("ffmpeg"):
        _render_with_ffmpeg(src, rate, dst)
    else:
        raise StretchError(
            "Neither rubberband nor ffmpeg is available. Install rubberband "
            "(recommended) or ffmpeg to enable pitch-preserved playback rate."
        )

    _prune_cache_to_limit()
    return dst
