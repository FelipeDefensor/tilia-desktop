"""On-disk cache for audiowave LOD pyramids.

The pyramid is cheap to use but expensive to build (read whole audio
file, aggregate min/max per bucket, build mip-map). Caching the pyramid
itself — not the source audio — keeps the cache small (a 2 h mono signal
at fpp=128 is ~12 MB vs ~700 MB of WAV) while sparing the second open
of any media we have already analysed.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tilia import dirs
from tilia.log import logger

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PyramidPayload:
    lod_min: list[np.ndarray]
    lod_max: list[np.ndarray]
    samplerate: int
    total_frames: int
    frames_per_peak: int


def cache_dir() -> Path:
    return Path(dirs.audiowave_pyramid_cache_path)


def _cache_dir_initialized() -> bool:
    """``setup_dirs`` populates the path; before that (e.g. CLI smoke runs
    that don't bootstrap the data dir) it's an empty Path() that resolves
    to the cwd. Using cwd as a cache dir would scatter .npz files in the
    project root, so we treat unset as "no cache available"."""
    return Path(dirs.audiowave_pyramid_cache_path) != Path()


def key_for_local_file(path: str | os.PathLike, frames_per_peak: int) -> str:
    """Stable key for a local audio/video file.

    Includes mtime + size so editing the file invalidates the cache; includes
    frames_per_peak so changing the setting produces a separate entry instead
    of clobbering the old one.
    """
    p = Path(path)
    stat = p.stat()
    payload = (
        f"file:{p.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:{frames_per_peak}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def key_for_youtube(video_id: str, frames_per_peak: int) -> str:
    payload = f"yt:{video_id}:{frames_per_peak}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _cache_file(key: str) -> Path:
    return cache_dir() / f"{key}.npz"


def load(key: str) -> PyramidPayload | None:
    if not _cache_dir_initialized():
        return None
    path = _cache_file(key)
    if not path.exists():
        return None
    try:
        with np.load(path) as data:
            if int(data["schema_version"]) != SCHEMA_VERSION:
                return None
            n_levels = int(data["n_levels"])
            lod_min = [data[f"min_{i}"] for i in range(n_levels)]
            lod_max = [data[f"max_{i}"] for i in range(n_levels)]
            return PyramidPayload(
                lod_min=lod_min,
                lod_max=lod_max,
                samplerate=int(data["samplerate"]),
                total_frames=int(data["total_frames"]),
                frames_per_peak=int(data["frames_per_peak"]),
            )
    except Exception:
        # Corrupt or partial file (interrupted write, version mismatch
        # we don't recognise). Drop it and treat as cache miss.
        logger.warning("audiowave pyramid cache: failed to load %s; removing", path)
        try:
            path.unlink()
        except OSError:
            pass
        return None


def save(key: str, payload: PyramidPayload) -> None:
    """Atomic write — temp file in the same directory, then os.replace.

    Same-directory temp is deliberate: cross-filesystem moves aren't atomic.
    """
    if not _cache_dir_initialized():
        return
    cache_dir().mkdir(parents=True, exist_ok=True)
    final = _cache_file(key)
    arrays: dict[str, np.ndarray] = {
        "schema_version": np.int32(SCHEMA_VERSION),
        "samplerate": np.int32(payload.samplerate),
        "total_frames": np.int64(payload.total_frames),
        "frames_per_peak": np.int32(payload.frames_per_peak),
        "n_levels": np.int32(len(payload.lod_min)),
    }
    for i, (mn, mx) in enumerate(zip(payload.lod_min, payload.lod_max)):
        arrays[f"min_{i}"] = mn.astype(np.float32, copy=False)
        arrays[f"max_{i}"] = mx.astype(np.float32, copy=False)

    # np.savez auto-appends ".npz", so pass it a path that already ends
    # in .npz to keep the actual filename predictable.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(cache_dir()), prefix=f".{final.name}.", suffix=".npz"
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        np.savez(tmp_path, **arrays)
        os.replace(tmp_path, final)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def evict_to_cap(max_bytes: int) -> int:
    """LRU eviction by mtime. Returns bytes freed.

    Called opportunistically (e.g. after writing a new entry); keeps the
    sweep cheap by stat-ing the cache dir directly rather than maintaining
    an index.
    """
    if max_bytes <= 0 or not _cache_dir_initialized():
        return 0
    d = cache_dir()
    if not d.exists():
        return 0
    entries: list[tuple[float, int, Path]] = []
    total = 0
    for f in d.glob("*.npz"):
        try:
            st = f.stat()
        except OSError:
            continue
        entries.append((st.st_mtime, st.st_size, f))
        total += st.st_size
    if total <= max_bytes:
        return 0
    entries.sort(key=lambda e: e[0])  # oldest first
    freed = 0
    for _, size, f in entries:
        if total - freed <= max_bytes:
            break
        try:
            f.unlink()
            freed += size
        except OSError:
            continue
    return freed
