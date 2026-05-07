import argparse
import os
import sys
import traceback

from PySide6.QtWidgets import QApplication

import tilia.errors
import tilia.utils  # noqa: F401
from tilia.app import App
from tilia.clipboard import Clipboard
from tilia.dirs import setup_dirs
from tilia.file.autosave import AutoSaver
from tilia.file.file_manager import FileManager
from tilia.log import logger
from tilia.media.player import QtAudioPlayer
from tilia.undo_manager import UndoManager

app = None
ui = None


def handle_exception(type, value, tb):
    if type in (EOFError, KeyboardInterrupt) and ui:
        ui.exit(1, type.__name__)

    exc_message = "".join(traceback.format_exception(type, value, tb))
    if ui:
        ui.show_crash_dialog(exc_message)
    if app:
        logger.file_dump(app.get_app_state())

    logger.critical(exc_message)
    if ui:
        ui.exit(1)


def boot():
    sys.excepthook = handle_exception

    args = setup_parser()
    setup_dirs()
    logger.setup()
    q_application = QApplication(sys.argv)
    global app, ui
    app = setup_logic()
    ui = setup_ui(q_application, args.user_interface)
    logger.debug("INITIALISED")
    if os.environ.get("ENVIRONMENT") == "dev":
        try:
            # icecream is a replacement for print()
            # Not required, but very useful for debugging.
            # Docs: https://github.com/gruns/icecream
            import icecream

            icecream.install()
        except ImportError:
            pass
    # has to be done after ui has been created, so timelines will get displayed
    if file := get_initial_file(args.file):
        app.on_open(file)
    else:
        app.setup_file()

    ui.launch()


def setup_parser():
    parser = argparse.ArgumentParser(exit_on_error=False)
    # `file` is positional so the OS can pass a .tla path (e.g. via Windows'
    # "Open with"), and `--file` is kept for backwards compatibility.
    parser.add_argument("file_pos", nargs="?", default="")
    parser.add_argument("--file", dest="file_flag", default="")
    parser.add_argument("--user-interface", "-i", choices=["qt", "cli"], default="qt")
    args = parser.parse_args()
    args.file = args.file_flag or args.file_pos
    return args


def setup_logic(autosaver=True):
    file_manager = FileManager()
    clipboard = Clipboard()
    undo_manager = UndoManager()
    player = QtAudioPlayer()

    _app = App(
        file_manager=file_manager,
        clipboard=clipboard,
        undo_manager=undo_manager,
        player=player,
    )

    if autosaver:
        AutoSaver(_app.get_app_state)

    return _app


def setup_ui(q_application: QApplication, interface: str):
    if interface == "qt":
        from tilia.ui.qtui import QtUI, TiliaMainWindow

        mw = TiliaMainWindow()
        return QtUI(q_application, mw)

    elif interface == "cli":
        from tilia.ui.cli.ui import CLI

        return CLI()


def get_initial_file(file: str):
    """
    Checks if a file path was passed as an argument to process.
    If it was, returns its path. Else, returns the empty string.
    Errors are displayed to the user via `OPEN_FILE_*`; the actual
    "is this a valid .tla?" check is delegated to `open_tla`.
    """
    if not file:
        return ""

    if not os.path.isfile(file):
        tilia.errors.display(tilia.errors.OPEN_FILE_NOT_FOUND, file)
        return ""

    if not file.endswith(".tla"):
        tilia.errors.display(
            tilia.errors.OPEN_FILE_INVALID_TLA, file, "Expected a .tla file."
        )
        return ""

    return file
