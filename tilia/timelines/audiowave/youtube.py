"""yt-dlp integration for the audiowave timeline.

yt-dlp is an optional dependency. If it isn't installed we degrade
gracefully (no waveform for YT URLs, but the YT player still works).
The first time we successfully reach a download, we surface a one-time
disclaimer modal; the user can dismiss it permanently.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

import tilia.constants
from tilia.log import logger
from tilia.exceptions import NoReplyToRequest
from tilia.requests import Get, get
from tilia.settings import settings
from tilia.timelines.audiowave.extract import extract_peaks_via_ffmpeg
from tilia.timelines.audiowave.peaks import CancelToken


# Generous total wall-clock cap. yt-dlp is bandwidth-bound, so even
# multi-hour audio streams typically finish well inside this. The
# timeout guards against a stalled connection hanging the worker
# forever; the user-visible cancel path is faster (poll interval below).
YT_DLP_TOTAL_TIMEOUT_SECONDS = 600
YT_DLP_POLL_INTERVAL = 0.2
YT_DLP_TERMINATE_GRACE_SECONDS = 2.0


class YTDownloadCancelled(Exception):
    """Raised when the user cancels an in-flight yt-dlp download.

    Suppressed by the worker (it checks ``CancelToken.cancelled`` before
    emitting errors) — this exists for clarity in logs and tests."""


def get_video_id(url: str) -> str | None:
    match = re.match(tilia.constants.YOUTUBE_URL_REGEX, url)
    return match[6] if match else None


def _yt_dlp_binary() -> str | None:
    return shutil.which("yt-dlp")


def _yt_dlp_module_importable() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False


def yt_dlp_command() -> list[str] | None:
    """Return the argv prefix that invokes yt-dlp, or None if unavailable.

    Prefer the standalone binary on PATH (works even when our embedded
    interpreter doesn't have the Python package installed). Fall back to
    ``<sys.executable> -m yt_dlp`` when only the Python module is
    importable. Using ``sys.executable`` (not bare ``python``) matters
    for venv installs where ``python`` may resolve to a different
    interpreter than ours."""
    binary = _yt_dlp_binary()
    if binary is not None:
        return [binary]
    if _yt_dlp_module_importable():
        return [sys.executable, "-m", "yt_dlp"]
    return None


def is_yt_dlp_available() -> bool:
    return yt_dlp_command() is not None


def acknowledge_terms_or_cancel() -> bool:
    """Return True if the user has already acknowledged or just OK'd
    the disclaimer. False means we should not proceed."""
    if settings.get("audiowave_timeline", "acknowledged_yt_dlp_terms"):
        return True
    try:
        accepted, dont_show_again = get(Get.FROM_USER_YT_DLP_ACKNOWLEDGEMENT)
    except NoReplyToRequest:
        # Headless / no UI to ask. Treat as not-acknowledged → don't
        # silently download on the user's behalf.
        return False
    if accepted and dont_show_again:
        settings.set("audiowave_timeline", "acknowledged_yt_dlp_terms", True)
    return accepted


def _terminate_proc(proc: subprocess.Popen) -> None:
    """Best-effort terminate-then-kill, swallowing OSError."""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except OSError:
        return
    try:
        proc.wait(timeout=YT_DLP_TERMINATE_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except OSError:
        return
    try:
        proc.wait(timeout=YT_DLP_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def _cleanup_tmp(tmp_path: str) -> None:
    """Remove tmp_path and any sibling that yt-dlp suffixed."""
    parent = os.path.dirname(tmp_path)
    base = os.path.basename(tmp_path)
    try:
        entries = os.listdir(parent)
    except OSError:
        return
    for entry in entries:
        if entry == base or entry.startswith(base):
            try:
                os.unlink(os.path.join(parent, entry))
            except OSError:
                pass


def download_audio_to_tempfile(
    url: str,
    cancel: CancelToken | None = None,
    timeout_seconds: float = YT_DLP_TOTAL_TIMEOUT_SECONDS,
) -> str:
    """Download YT audio to a temp file. Caller deletes when done.

    Implemented as a subprocess of `python -m yt_dlp` rather than the
    in-process API — yt-dlp's Python API has rough edges around
    cancellation and stderr capture; the subprocess gives us a clean
    Popen handle for ``terminate()`` on user-cancel.
    """
    fd, tmp_path = tempfile.mkstemp(suffix=".m4a", prefix="tilia_yt_")
    os.close(fd)
    # yt-dlp will refuse to overwrite an existing file by default; remove
    # the placeholder so it can write fresh.
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    invocation = yt_dlp_command()
    if invocation is None:
        raise RuntimeError("yt-dlp is not installed")
    cmd = [
        *invocation,
        "-f",
        "bestaudio",
        "-o",
        tmp_path,
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        url,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    start = time.monotonic()
    try:
        while True:
            if proc.poll() is not None:
                break
            if cancel is not None and cancel.cancelled:
                _terminate_proc(proc)
                _cleanup_tmp(tmp_path)
                raise YTDownloadCancelled("yt-dlp download cancelled")
            if time.monotonic() - start > timeout_seconds:
                _terminate_proc(proc)
                _cleanup_tmp(tmp_path)
                raise RuntimeError(
                    f"yt-dlp download exceeded {timeout_seconds:.0f}s timeout"
                )
            time.sleep(YT_DLP_POLL_INTERVAL)
    except BaseException:
        _terminate_proc(proc)
        raise

    if proc.returncode != 0:
        stderr = ""
        if proc.stderr is not None:
            try:
                stderr = proc.stderr.read() or ""
            except OSError:
                pass
        _cleanup_tmp(tmp_path)
        raise RuntimeError(
            f"yt-dlp exited with code {proc.returncode}: {stderr.strip()}"
        )
    # yt-dlp may add an extension if the source format differs. Find
    # the actual file by scanning the parent dir.
    if os.path.exists(tmp_path):
        return tmp_path
    parent = os.path.dirname(tmp_path)
    base = os.path.basename(tmp_path)
    for entry in os.listdir(parent):
        if entry.startswith(base):
            return os.path.join(parent, entry)
    raise RuntimeError(f"yt-dlp produced no output file at {tmp_path}")


def extract_peaks_via_yt_dlp(
    url: str,
    frames_per_peak: int,
    cancel: CancelToken | None = None,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Download the audio stream from ``url`` and reuse the ffmpeg
    streaming pipeline to compute peaks.

    Requires both yt-dlp (optional) and ffmpeg (already required for
    local video). Raises ``RuntimeError`` on any failure.
    """
    if not is_yt_dlp_available():
        raise RuntimeError("yt-dlp is not installed")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not installed")
    # The disclaimer modal must be shown on the main thread before
    # work reaches this worker. AudioWaveTimeline.refresh() is the
    # only call site and gates submission on
    # acknowledge_terms_or_cancel(); we don't re-check the persisted
    # setting here because "accepted once without 'don't show again'"
    # leaves the setting False, and re-checking would spuriously fail
    # in that legitimate case.

    tmp_path = download_audio_to_tempfile(url, cancel=cancel)
    try:
        return extract_peaks_via_ffmpeg(tmp_path, frames_per_peak, cancel)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            logger.warning(
                "audiowave yt: failed to clean up temp file %s", tmp_path
            )
