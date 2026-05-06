"""One-time disclaimer for YouTube audio extraction via yt-dlp.

Shown the first time the user opens an audiowave timeline against a
YouTube URL. The "Don't show this again" checkbox persists acceptance
in settings so subsequent opens skip the prompt entirely.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QMessageBox

from tilia.requests import Get, get

DISCLAIMER_TITLE = "YouTube audio extraction"
DISCLAIMER_TEXT = (
    "TiLiA can use yt-dlp to extract audio from YouTube videos for "
    "waveform display.\n\n"
    "Downloading content from YouTube may be subject to YouTube's Terms "
    "of Service and the copyright of the content. Use this feature only "
    "with content you have the right to access for analytical purposes "
    "(fair use, public domain, your own uploads, etc.).\n\n"
    "TiLiA does not redistribute downloaded content; the audio cache is "
    "stored locally on your machine."
)


def ask_yt_dlp_acknowledgement() -> tuple[bool, bool]:
    """Show the disclaimer modal.

    Returns ``(accepted, dont_show_again)``. ``accepted`` is True iff
    the user clicked OK. ``dont_show_again`` is True iff they also
    ticked the checkbox.
    """
    box = QMessageBox(
        QMessageBox.Icon.Information,
        DISCLAIMER_TITLE,
        DISCLAIMER_TEXT,
        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        get(Get.MAIN_WINDOW),
    )
    box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    checkbox = QCheckBox("Don't show this again")
    box.setCheckBox(checkbox)
    accepted = box.exec() == QMessageBox.StandardButton.Ok
    dont_show_again = checkbox.isChecked() and accepted
    return accepted, dont_show_again
