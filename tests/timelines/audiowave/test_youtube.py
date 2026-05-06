from unittest.mock import patch

import pytest

from tilia.requests import Get
from tilia.requests.get import _requests_to_callbacks
from tilia.settings import settings
from tilia.timelines.audiowave import youtube


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

    def test_unacknowledged_raises_without_invoking_dialog(self):
        # The disclaimer modal is built on the main thread by the timeline
        # before submitting work to the pool. The worker entry point must
        # NOT trigger the dialog itself (NSWindow main-thread assertion on
        # macOS), so an unacknowledged setting raises immediately.
        settings.set("audiowave_timeline", "acknowledged_yt_dlp_terms", False)
        with patch(
            "tilia.timelines.audiowave.youtube.is_yt_dlp_available",
            return_value=True,
        ), patch(
            "tilia.timelines.audiowave.youtube.shutil.which", return_value="/x"
        ):
            with pytest.raises(RuntimeError, match="acknowledged"):
                youtube.extract_peaks_via_yt_dlp("https://yt.com/x", 128)
