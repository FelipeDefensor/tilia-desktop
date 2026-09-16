import argparse
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tilia.boot import get_initial_file, setup_parser


class TestGetInitialFilePath:
    def test_get_initial_file_no_file(self):
        assert get_initial_file("", MagicMock()) == ""

    def test_get_initial_file_path_does_not_exist(self):
        error = MagicMock()
        get_initial_file("inexistent.tla", error)
        error.assert_called_once()

    def test_get_initial_file_path_with_non_tla_extension(self):
        error = MagicMock()
        get_initial_file(str(Path(__file__)), error)
        error.assert_called_once()

    def test_get_initial_file_path_good_path(self, tmp_path):
        file_path = tmp_path / "test.tla"
        file_path.touch()
        error = MagicMock()
        result = get_initial_file(str(file_path.resolve()), error)
        assert Path(result) == Path(file_path)
        error.assert_not_called()

    @pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows-specific")
    def test_accepts_backslash(self, tmp_path):
        file_path = tmp_path / "test.tla"
        file_path.touch()
        win_path = str(file_path)  # on Windows, str(Path) uses backslashes
        assert "\\" in win_path
        error = MagicMock()
        assert get_initial_file(win_path, error) == win_path
        error.assert_not_called()


class TestGetSetupParser:
    def test_setup_parser_default_values(self):
        sys.argv = ["main.py"]

        args = setup_parser()

        assert args.file == ""
        assert args.user_interface == "qt"

    def test_setup_parser_custom_values(self, tmp_path):
        file_path = tmp_path / "test.tla"
        file_path.touch()
        posix_path = file_path.as_posix()

        sys.argv = ["script.py", posix_path, "--user-interface", "cli"]

        args = setup_parser()

        assert args.file == posix_path
        assert args.user_interface == "cli"

    def test_setup_parser_user_interface_cli(self):
        sys.argv = ["main.py", "--user-interface", "cli"]

        args = setup_parser()

        assert args.file == ""
        assert args.user_interface == "cli"

    def test_setup_parser_invalid_user_interface_choice(self):
        sys.argv = ["main.py", "--user-interface", "INVALID"]

        with pytest.raises(argparse.ArgumentError):
            setup_parser()

    def test_setup_parser_file_after_interface_flag(self, tmp_path):
        file_path = tmp_path / "test.tla"
        file_path.touch()
        posix_path = file_path.as_posix()

        sys.argv = ["main.py", "--user-interface", "cli", posix_path]

        args = setup_parser()

        assert args.file == posix_path
        assert args.user_interface == "cli"

    def test_setup_parser_nonexistent_file_raises(self):
        sys.argv = ["main.py", "nonexistent.tla"]

        with pytest.raises(SystemExit):
            setup_parser()

    def test_setup_parser_wrong_extension_raises(self, tmp_path):
        file_path = tmp_path / "test.txt"
        file_path.touch()

        sys.argv = ["main.py", file_path.as_posix()]

        with pytest.raises(SystemExit):
            setup_parser()

    @pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows-specific")
    def test_setup_parser_accepts_backslash(self, tmp_path):
        file_path = tmp_path / "test.tla"
        file_path.touch()
        win_path = str(file_path)  # on Windows, str(Path) uses backslashes
        sys.argv = ["tilia.exe", win_path]

        args = setup_parser()

        assert args.file == win_path


class TestRelativeLaunchPath:
    def test_relative_file_argument_survives_setup_dirs(self, monkeypatch, tmp_path):
        """
        Regression test: setup_parser() (and
        its get_initial_file validation) runs while cwd is still the launch
        directory, but setup_dirs() used to chdir into the tilia package
        before the file was actually opened, so a relative positional file
        argument would pass argument parsing and then fail with "File not
        found" once the app tried to open it.
        """
        from tilia import dirs

        monkeypatch.chdir(tmp_path)
        sub_dir = tmp_path / "repro"
        sub_dir.mkdir()
        (sub_dir / "x.tla").touch()
        relative_path = os.path.join("repro", "x.tla")

        sys.argv = ["main.py", relative_path]
        args = setup_parser()
        assert args.file == relative_path

        # setup_dirs() writes to the real platformdirs locations; redirect
        # them under tmp_path so this test never touches the real ones.
        monkeypatch.setattr(dirs, "_SITE_DATA_DIR", tmp_path / "site_data")
        monkeypatch.setattr(dirs, "_USER_DATA_DIR", tmp_path / "user_data")
        monkeypatch.setattr(dirs, "autosaves_path", dirs.autosaves_path)
        monkeypatch.setattr(dirs, "logs_path", dirs.logs_path)

        dirs.setup_dirs()

        assert os.path.isfile(args.file)
