from pathlib import Path

from tests.utils import simulate_launch_dir


def run_script(cli, path):
    cli.parse_and_run(f'script "{str(path.resolve())}"')


def write_script(tmp_path, contents, encoding="utf-8"):
    path = tmp_path / "script.txt"
    path.write_text(contents, encoding=encoding)
    return path


def test_empty_script(cli, tmp_path, tilia_errors):
    path = write_script(tmp_path, "")
    run_script(cli, path)
    tilia_errors.assert_error()


def test_create_timelines(cli, tmp_path, tls):
    path = write_script(tmp_path, "timelines add hierarchy --name test")
    run_script(cli, path)

    assert len(tls) == 1
    assert tls[0].get_data("name") == "test"


def test_load_media(cli, tmp_path, tilia_state):
    media_path = Path(__file__).parent.parent.parent / "resources" / "example.mp3"
    path = write_script(tmp_path, f"load-media {str(media_path.resolve())}")
    run_script(cli, path)

    assert Path(tilia_state.media_path) == media_path


def test_comments(cli, tls, tmp_path, tilia_errors):
    script = "# this is a comment"
    script += "\ntimelines add hierarchy"
    script += "\n# this is another comment"
    path = write_script(tmp_path, script)

    run_script(cli, path)
    tilia_errors.assert_no_error()
    assert len(tls) == 1


def test_different_encoding(cli, tls, tmp_path, tilia_errors):
    path = write_script(
        tmp_path, "timelines add hierarchy --name Válido?", encoding="latin-1"
    )
    cli.parse_and_run(f'script "{str(path.resolve())}" --encoding latin-1')

    tilia_errors.assert_no_error()
    assert len(tls) == 1


def test_relative_script_path(cli, monkeypatch, tmp_path, tls):
    """
    Regression test: a relative `script`
    path must resolve against the directory TiLiA was launched from, not
    against the tilia package directory that setup_dirs() used to chdir
    into.
    """
    simulate_launch_dir(monkeypatch, tmp_path)
    write_script(tmp_path, "timelines add hierarchy --name test")

    cli.parse_and_run('script "script.txt"')

    assert len(tls) == 1
    assert tls[0].get_data("name") == "test"


def test_relative_path_inside_script(cli, monkeypatch, tmp_path):
    """
    Regression test: a relative path used
    inside a command run *from* a script (e.g. `save`) must also resolve
    against the original launch directory, not against the tilia package
    directory.
    """
    simulate_launch_dir(monkeypatch, tmp_path)
    path = write_script(tmp_path, 'save "relative_output.tla"')

    run_script(cli, path)

    assert (tmp_path / "relative_output.tla").exists()
