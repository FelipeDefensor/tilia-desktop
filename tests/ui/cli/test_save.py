import os
from io import StringIO
from pathlib import Path

import pytest

from tests.utils import simulate_launch_dir
from tilia.ui.path import ensure_tla_extension


@pytest.mark.parametrize(
    "path, expected",
    [
        ("file.txt", "file.txt.tla"),
        ("file", "file.tla"),
        ("file.tla", "file.tla"),
    ],
)
def test_ensure_tla_extension(path, expected):
    result = ensure_tla_extension(Path(path))
    assert str(result) == expected


def test_save(cli, tmp_path):
    path = tmp_path / "test.tla"
    cli.parse_and_run(f'save "{str(path.resolve())}"')
    assert os.listdir(tmp_path) == [path.name]


def test_save_parent_is_file_fails(cli, tmp_path, tilia_errors):
    parent = tmp_path / "parent"
    parent.touch()
    save_path = tmp_path / "parent" / "file.tla"
    cli.parse_and_run(f'save "{str(save_path.resolve())}"')
    tilia_errors.assert_error()
    assert not save_path.exists()


def test_save_parent_doesnt_exist_fails(cli, tmp_path, tilia_errors):
    save_path = tmp_path / "parent" / "file.tla"
    cli.parse_and_run(f'save "{str(save_path.resolve())}"')
    tilia_errors.assert_error()
    assert not save_path.exists()


def test_save_overwrite_flag(cli, tmp_path):
    path = tmp_path / "file.tla"
    path.write_text("content")
    cli.parse_and_run(f'save "{str(path.resolve())}" --overwrite')
    assert path.read_text() != "content"


def test_save_overwrite_yes(cli, monkeypatch, tmp_path):
    path = tmp_path / "file.tla"
    path.write_text("content")
    monkeypatch.setattr("sys.stdin", StringIO("yes\n"))
    cli.parse_and_run(f'save "{str(path.resolve())}"')
    assert path.read_text() != "content"


def test_save_overwrite_no(cli, monkeypatch, tmp_path):
    path = tmp_path / "file.tla"
    path.write_text("content")
    monkeypatch.setattr("sys.stdin", StringIO("no\n"))
    cli.parse_and_run(f'save "{str(path.resolve())}"')
    assert path.read_text() == "content"


def test_save_invalid_save_path(cli, tmp_path, tilia_errors):
    path = tmp_path / "invalid" / "file.tla"
    cli.parse_and_run(f'save "{str(path.resolve())}"')
    tilia_errors.assert_error()


def test_save_relative_path(cli, monkeypatch, tmp_path):
    """
    Regression test: a relative path given to
    `save` must resolve against the directory TiLiA was launched from, not
    against the tilia package directory that setup_dirs() used to chdir
    into.
    """
    simulate_launch_dir(monkeypatch, tmp_path)

    cli.parse_and_run('save "relative.tla"')

    assert (tmp_path / "relative.tla").exists()
