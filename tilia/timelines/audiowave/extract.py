"""Stream-extract audio from a video file via ffmpeg, computing waveform
peaks on the fly. No intermediate WAV file ever lands on disk."""

from __future__ import annotations

import shutil
import subprocess

import numpy as np

from tilia.timelines.audiowave.peaks import CancelToken

# Output samplerate is fixed at 44.1 kHz mono regardless of source. The
# waveform display only needs amplitude envelope; resampling artefacts
# at this rate are inaudible to the eye.
TARGET_SAMPLERATE = 44100


def is_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def extract_peaks_via_ffmpeg(
    path: str,
    frames_per_peak: int,
    cancel: CancelToken | None = None,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Run ffmpeg to decode + downmix + resample audio, aggregating min/max
    peaks per bucket as samples arrive on stdout.

    Returns ``(peaks_min, peaks_max, samplerate, total_frames)`` matching
    ``peaks.compute_peaks_sync``. Raises ``RuntimeError`` if ffmpeg returns
    a non-zero exit code (and we weren't cancelled). Cancellation closes
    stdout and terminates the process.
    """
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        path,
        "-vn",  # no video
        "-ac",
        "1",  # downmix to mono
        "-ar",
        str(TARGET_SAMPLERATE),
        "-f",
        "s16le",
        "-",
    ]
    # stderr=DEVNULL because we read stdout incrementally — letting stderr
    # buffer up to the OS pipe limit could deadlock the writer. Loss of
    # diagnostic detail is acceptable; the return code routes the failure
    # to AUDIOWAVE_INVALID_FILE.
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )

    chunk_bytes = max(1, frames_per_peak) * 2  # int16 = 2 bytes / frame
    mins: list[int] = []
    maxs: list[int] = []
    total_frames = 0
    try:
        while True:
            if cancel is not None and cancel.cancelled:
                proc.terminate()
                break
            assert proc.stdout is not None
            data = proc.stdout.read(chunk_bytes)
            if not data:
                break
            arr = np.frombuffer(data, dtype=np.int16)
            if arr.size == 0:
                continue
            mins.append(int(arr.min()))
            maxs.append(int(arr.max()))
            total_frames += arr.size
        proc.wait()
    finally:
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except Exception:
                pass

    if proc.returncode not in (0, None) and not (cancel and cancel.cancelled):
        raise RuntimeError(
            f"ffmpeg exited with code {proc.returncode} for path {path!r}"
        )

    peaks_min = np.asarray(mins, dtype=np.float32) / 32768.0
    peaks_max = np.asarray(maxs, dtype=np.float32) / 32768.0
    abs_peak = max(
        float(np.abs(peaks_min).max(initial=0.0)),
        float(np.abs(peaks_max).max(initial=0.0)),
    )
    if abs_peak > 0:
        peaks_min = peaks_min / abs_peak
        peaks_max = peaks_max / abs_peak
    return peaks_min, peaks_max, TARGET_SAMPLERATE, total_frames
