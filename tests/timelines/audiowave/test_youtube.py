import io
import subprocess
from unittest.mock import patch

import pytest

from tilia.requests import Get
from tilia.requests.get import _requests_to_callbacks
from tilia.settings import settings
from tilia.timelines.audiowave import youtube
from tilia.timelines.audiowave.peaks import CancelToken


def serve_yt_dlp_acknowledgement(reply):
    """Context-manager helper to short-circuit the modal."""

    class _Serve:
        def __enter__(self):
            self.previous = _requests_to_callbacks.get(
                Get.FROM_USER_YT_DLP_ACKNOWLEDGEMENT
            )
            _requests_to_callbacks[Get.FROM_USER_YT_DLP_ACKNOWLEDGEMENT] = (
                lambda: reply
            )
            return self

        def __exit__(self, *_):
            if self.previous is None:
                _requests_to_callbacks.pop(
                    Get.FROM_USER_YT_DLP_ACKNOWLEDGEMENT, None
                )
            else:
                _requests_to_callbacks[
                    Get.FROM_USER_YT_DLP_ACKNOWLEDGEMENT
                ] = self.previous

    return _Serve()


class TestVideoIdParse:
    def test_extracts_id_from_canonical_url(self):
        assert (
            youtube.get_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            == "dQw4w9WgXcQ"
        )

    def test_returns_none_for_non_youtube(self):
        assert youtube.get_video_id("https://example.com/foo") is None


class TestAvailability:
    def test_returns_bool(self):
        assert isinstance(youtube.is_yt_dlp_available(), bool)

    def test_binary_on_path_is_sufficient(self):
        # When yt-dlp ships as a standalone binary (e.g. system pipx
        # install), the embedded venv may not have the Python module
        # importable. Detection must still report available.
        with patch(
            "tilia.timelines.audiowave.youtube._yt_dlp_binary",
            return_value="/usr/local/bin/yt-dlp",
        ), patch(
            "tilia.timelines.audiowave.youtube._yt_dlp_module_importable",
            return_value=False,
        ):
            assert youtube.is_yt_dlp_available() is True
            assert youtube.yt_dlp_command() == ["/usr/local/bin/yt-dlp"]

    def test_module_only_falls_back_to_python_m(self):
        with patch(
            "tilia.timelines.audiowave.youtube._yt_dlp_binary",
            return_value=None,
        ), patch(
            "tilia.timelines.audiowave.youtube._yt_dlp_module_importable",
            return_value=True,
        ):
            cmd = youtube.yt_dlp_command()
            assert cmd is not None
            assert cmd[1:] == ["-m", "yt_dlp"]
            # First element is the running interpreter, not bare "python".
            import sys

            assert cmd[0] == sys.executable

    def test_neither_returns_none(self):
        with patch(
            "tilia.timelines.audiowave.youtube._yt_dlp_binary",
            return_value=None,
        ), patch(
            "tilia.timelines.audiowave.youtube._yt_dlp_module_importable",
            return_value=False,
        ):
            assert youtube.yt_dlp_command() is None
            assert youtube.is_yt_dlp_available() is False


class TestAcknowledgement:
    def test_acknowledged_setting_skips_dialog(self):
        settings.set("audiowave_timeline", "acknowledged_yt_dlp_terms", True)
        try:
            # Even with no Serve handler, this should return True without
            # ever invoking the dialog.
            assert youtube.acknowledge_terms_or_cancel() is True
        finally:
            settings.set("audiowave_timeline", "acknowledged_yt_dlp_terms", False)

    def test_dialog_accept_with_dont_show_again_persists(self):
        settings.set("audiowave_timeline", "acknowledged_yt_dlp_terms", False)
        with serve_yt_dlp_acknowledgement((True, True)):
            assert youtube.acknowledge_terms_or_cancel() is True
        try:
            assert (
                settings.get("audiowave_timeline", "acknowledged_yt_dlp_terms")
                is True
            )
        finally:
            settings.set("audiowave_timeline", "acknowledged_yt_dlp_terms", False)

    def test_dialog_accept_without_dont_show_again_does_not_persist(self):
        settings.set("audiowave_timeline", "acknowledged_yt_dlp_terms", False)
        with serve_yt_dlp_acknowledgement((True, False)):
            assert youtube.acknowledge_terms_or_cancel() is True
        # Setting was not flipped — next time we'd ask again.
        assert (
            settings.get("audiowave_timeline", "acknowledged_yt_dlp_terms")
            is False
        )

    def test_dialog_cancel_returns_false(self):
        settings.set("audiowave_timeline", "acknowledged_yt_dlp_terms", False)
        with serve_yt_dlp_acknowledgement((False, False)):
            assert youtube.acknowledge_terms_or_cancel() is False

    def test_no_dialog_handler_returns_false(self):
        settings.set("audiowave_timeline", "acknowledged_yt_dlp_terms", False)
        # Ensure no handler is registered.
        _requests_to_callbacks.pop(Get.FROM_USER_YT_DLP_ACKNOWLEDGEMENT, None)
        assert youtube.acknowledge_terms_or_cancel() is False


class TestExtractGuards:
    def test_missing_yt_dlp_raises(self):
        with patch(
            "tilia.timelines.audiowave.youtube.is_yt_dlp_available",
            return_value=False,
        ):
            with pytest.raises(RuntimeError, match="yt-dlp"):
                youtube.extract_peaks_via_yt_dlp("https://yt.com/x", 128)

    def test_missing_ffmpeg_raises(self):
        with patch(
            "tilia.timelines.audiowave.youtube.is_yt_dlp_available",
            return_value=True,
        ), patch(
            "tilia.timelines.audiowave.youtube.shutil.which", return_value=None
        ):
            with pytest.raises(RuntimeError, match="ffmpeg"):
                youtube.extract_peaks_via_yt_dlp("https://yt.com/x", 128)

    def test_passes_cancel_token_to_downloader(self):
        # The worker's CancelToken must thread through to the download
        # subprocess so user-cancel during YT extraction can terminate
        # in-flight network IO.
        seen = {}

        def _capture(url, cancel=None):
            seen["url"] = url
            seen["cancel"] = cancel
            return "/tmp/x.m4a"

        token = CancelToken()
        with patch(
            "tilia.timelines.audiowave.youtube.is_yt_dlp_available",
            return_value=True,
        ), patch(
            "tilia.timelines.audiowave.youtube.shutil.which", return_value="/x"
        ), patch(
            "tilia.timelines.audiowave.youtube.download_audio_to_tempfile",
            side_effect=_capture,
        ), patch(
            "tilia.timelines.audiowave.youtube.extract_peaks_via_ffmpeg",
            return_value=(None, None, 44100, 0),
        ), patch(
            "tilia.timelines.audiowave.youtube.os.unlink"
        ):
            youtube.extract_peaks_via_yt_dlp(
                "https://yt.com/x", 128, cancel=token
            )

        assert seen["cancel"] is token

    def test_extract_does_not_invoke_dialog(self):
        # The disclaimer is shown on the main thread by the timeline
        # before submitting work to the pool. The worker entry point
        # must never trigger the dialog itself (NSWindow main-thread
        # assertion on macOS) and must not block on the persisted
        # setting either — accepting "OK" without ticking
        # "don't show again" is a valid path that leaves the setting
        # False but should still produce a waveform.
        settings.set("audiowave_timeline", "acknowledged_yt_dlp_terms", False)
        download_calls = []

        with patch(
            "tilia.timelines.audiowave.youtube.is_yt_dlp_available",
            return_value=True,
        ), patch(
            "tilia.timelines.audiowave.youtube.shutil.which", return_value="/x"
        ), patch(
            "tilia.timelines.audiowave.youtube.download_audio_to_tempfile",
            side_effect=lambda url, cancel=None: download_calls.append(url)
            or "/tmp/x.m4a",
        ), patch(
            "tilia.timelines.audiowave.youtube.extract_peaks_via_ffmpeg",
            return_value=(None, None, 44100, 0),
        ), patch(
            "tilia.timelines.audiowave.youtube.os.unlink"
        ), serve_yt_dlp_acknowledgement((False, False)):
            # serve_yt_dlp_acknowledgement is wired but should never
            # be invoked from the worker entry point.
            youtube.extract_peaks_via_yt_dlp("https://yt.com/x", 128)

        assert download_calls == ["https://yt.com/x"]


class _FakePopen:
    """Minimal subprocess.Popen stand-in for download tests.

    ``poll_responses`` is a list of return values for successive
    ``poll()`` calls. None means "still running"; an int means "exited
    with that returncode". After the list is exhausted the process is
    treated as exited with the last value (or 0)."""

    def __init__(self, poll_responses, stderr_text=""):
        self._responses = list(poll_responses)
        self.returncode = None
        self.stderr = io.StringIO(stderr_text)
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        if self._responses:
            value = self._responses.pop(0)
            if value is not None:
                self.returncode = value
            return value
        # Drained: behave as if the process exited with its last
        # observed returncode (or 0 if we never saw one).
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1
        # On terminate, the next poll should report exit.
        self.returncode = -15
        self._responses = [-15]

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9
        self._responses = [-9]

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class TestDownloadCancellation:
    def test_cancel_terminates_process(self, tmp_path):
        token = CancelToken()
        # Process is "running" on first poll; before the second poll we
        # flip the cancel flag.
        responses = [None, None, None]
        fake = _FakePopen(responses)

        def _make_popen(*_args, **_kwargs):
            # Set cancel flag mid-loop so we hit the cancel branch.
            token.cancelled = True
            return fake

        with patch(
            "tilia.timelines.audiowave.youtube.yt_dlp_command",
            return_value=["/usr/bin/yt-dlp"],
        ), patch(
            "tilia.timelines.audiowave.youtube.subprocess.Popen",
            side_effect=_make_popen,
        ), patch(
            "tilia.timelines.audiowave.youtube.time.sleep"
        ):
            with pytest.raises(youtube.YTDownloadCancelled):
                youtube.download_audio_to_tempfile(
                    "https://yt.com/x", cancel=token
                )

        assert fake.terminate_calls == 1

    def test_timeout_terminates_process(self):
        # Simulate elapsed time blowing past the timeout while poll
        # keeps reporting "still running".
        fake = _FakePopen([None] * 10)
        # First call inside Popen is start-time; subsequent calls in
        # the loop must exceed the timeout.
        times = iter([0.0, 0.1, 9999.0, 9999.0, 9999.0])

        with patch(
            "tilia.timelines.audiowave.youtube.yt_dlp_command",
            return_value=["/usr/bin/yt-dlp"],
        ), patch(
            "tilia.timelines.audiowave.youtube.subprocess.Popen",
            return_value=fake,
        ), patch(
            "tilia.timelines.audiowave.youtube.time.monotonic",
            side_effect=lambda: next(times),
        ), patch(
            "tilia.timelines.audiowave.youtube.time.sleep"
        ):
            with pytest.raises(RuntimeError, match="timeout"):
                youtube.download_audio_to_tempfile(
                    "https://yt.com/x", timeout_seconds=5
                )

        assert fake.terminate_calls == 1

    def test_nonzero_exit_raises_with_stderr(self):
        fake = _FakePopen([None, 1], stderr_text="boom")
        with patch(
            "tilia.timelines.audiowave.youtube.yt_dlp_command",
            return_value=["/usr/bin/yt-dlp"],
        ), patch(
            "tilia.timelines.audiowave.youtube.subprocess.Popen",
            return_value=fake,
        ), patch(
            "tilia.timelines.audiowave.youtube.time.sleep"
        ):
            with pytest.raises(RuntimeError, match="boom"):
                youtube.download_audio_to_tempfile("https://yt.com/x")

        # Failure path should not terminate (process exited on its own).
        assert fake.terminate_calls == 0
