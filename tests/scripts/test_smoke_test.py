"""
Tests for scripts/smoke_test.py.

The script under test is a standalone, stdlib-only file (not part of the
`tilia` package), so it's loaded here by adding `scripts/` to `sys.path`
rather than by installing it. Every process-based check is exercised
against tiny fake "executables" -- Python scripts run via `sys.executable`
-- instead of a real TiLiA build, so these tests are fast and don't need a
Nuitka build. All waits are kept at or under 1 second.
"""

import os
import plistlib
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import smoke_test  # noqa: E402


def _write_fake_exe(tmp_path: Path, name: str, body: str) -> list[str]:
    script = tmp_path / name
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(script)]


# --------------------------------------------------------------------------
# check_gui
# --------------------------------------------------------------------------


def test_check_gui_healthy_process_passes(tmp_path):
    cmd = _write_fake_exe(tmp_path, "gui_healthy.py", "import time\ntime.sleep(5)\n")
    result = smoke_test.check_gui(cmd, 0.3, log_path=tmp_path / "out.log")
    assert result.passed is True


def test_check_gui_early_exit_fails(tmp_path):
    cmd = _write_fake_exe(tmp_path, "gui_early_exit.py", "import sys\nsys.exit(0)\n")
    result = smoke_test.check_gui(cmd, 0.3, log_path=tmp_path / "out.log")
    assert result.passed is False
    assert "exited early" in result.detail


def test_check_gui_traceback_while_alive_fails(tmp_path):
    cmd = _write_fake_exe(
        tmp_path,
        "gui_traceback.py",
        """
        import time
        print("Traceback (most recent call last):", flush=True)
        print('  File "fake.py", line 1, in <module>', flush=True)
        print("Exception: boom", flush=True)
        time.sleep(5)
        """,
    )
    result = smoke_test.check_gui(cmd, 0.3, log_path=tmp_path / "out.log")
    assert result.passed is False
    assert "traceback" in result.detail.lower()


# --------------------------------------------------------------------------
# check_cli
# --------------------------------------------------------------------------


def test_check_cli_todays_argparse_error_passes(tmp_path):
    cmd = _write_fake_exe(
        tmp_path,
        "cli_today.py",
        """
        import sys
        print("Traceback (most recent call last):", file=sys.stderr)
        print(
            "argparse.ArgumentError: argument --user-interface/-i: "
            "invalid choice: 'cli' (choose from 'qt')",
            file=sys.stderr,
        )
        sys.exit(1)
        """,
    )
    result = smoke_test.check_cli(cmd, 0.3, log_path=tmp_path / "out.log")
    assert result.passed is True


def test_check_cli_hanging_fails(tmp_path):
    cmd = _write_fake_exe(tmp_path, "cli_hangs.py", "import time\ntime.sleep(5)\n")
    result = smoke_test.check_cli(cmd, 0.2, log_path=tmp_path / "out.log")
    assert result.passed is False
    assert "hung" in result.detail or "did not exit" in result.detail


def test_check_cli_missing_expected_message_fails(tmp_path):
    cmd = _write_fake_exe(
        tmp_path,
        "cli_wrong_message.py",
        """
        import sys
        print("some unrelated startup error", file=sys.stderr)
        sys.exit(1)
        """,
    )
    result = smoke_test.check_cli(cmd, 0.3, log_path=tmp_path / "out.log")
    assert result.passed is False
    assert "missing" in result.detail


def test_check_cli_exit_zero_fails(tmp_path):
    cmd = _write_fake_exe(tmp_path, "cli_exit_zero.py", "import sys\nsys.exit(0)\n")
    result = smoke_test.check_cli(cmd, 0.3, log_path=tmp_path / "out.log")
    assert result.passed is False
    assert "expected non-zero" in result.detail


# --------------------------------------------------------------------------
# check_file_arg
# --------------------------------------------------------------------------


def test_check_file_arg_skipped_without_file(tmp_path):
    cmd = [sys.executable, "-c", "pass"]
    result = smoke_test.check_file_arg(cmd, None, 0.3, log_path=tmp_path / "out.log")
    assert result.passed is None
    assert "no --file given" in result.detail


def test_check_file_arg_missing_path_fails(tmp_path):
    cmd = [sys.executable, "-c", "pass"]
    missing = tmp_path / "does_not_exist.tla"
    result = smoke_test.check_file_arg(cmd, missing, 0.3, log_path=tmp_path / "out.log")
    assert result.passed is False


def test_check_file_arg_alive_with_existing_file_passes(tmp_path):
    cmd = _write_fake_exe(tmp_path, "gui_with_file.py", "import time\ntime.sleep(5)\n")
    tla = tmp_path / "sample.tla"
    tla.write_text("{}", encoding="utf-8")
    result = smoke_test.check_file_arg(cmd, tla, 0.3, log_path=tmp_path / "out.log")
    assert result.passed is True


# --------------------------------------------------------------------------
# check_resources
# --------------------------------------------------------------------------


def test_check_resources_about_pass(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "LICENSE").write_text("GPL", encoding="utf-8")
    result = smoke_test.check_resources("resources_about", tmp_path, ["LICENSE"])
    assert result.passed is True


def test_check_resources_youtube_missing_file_fails(tmp_path):
    player_dir = tmp_path / "tilia" / "media" / "player"
    player_dir.mkdir(parents=True)
    (player_dir / "youtube.html").write_text("<html></html>", encoding="utf-8")
    # youtube.css is intentionally missing.
    result = smoke_test.check_resources(
        "resources_youtube", tmp_path, ["youtube.html", "youtube.css"]
    )
    assert result.passed is False
    assert "youtube.css" in result.detail


def test_check_resources_score_import_pass(tmp_path):
    score_dir = tmp_path / "tilia" / "parsers" / "score"
    score_dir.mkdir(parents=True)
    (score_dir / "svg_maker.html").write_text("<html></html>", encoding="utf-8")
    (score_dir / "timewise_to_partwise.xsl").write_text("<xsl/>", encoding="utf-8")
    result = smoke_test.check_resources(
        "resources_score", tmp_path, ["svg_maker.html", "timewise_to_partwise.xsl"]
    )
    assert result.passed is True


def test_check_resources_missing_root_is_skipped(tmp_path):
    result = smoke_test.check_resources(
        "resources_about", tmp_path / "nope", ["LICENSE"]
    )
    assert result.passed is None


def test_check_resources_none_root_is_skipped():
    result = smoke_test.check_resources("resources_about", None, ["LICENSE"])
    assert result.passed is None


# --------------------------------------------------------------------------
# Reporting: PASS/FAIL/SKIP lines, GitHub annotations, step summary
# --------------------------------------------------------------------------


def _sample_results():
    return [
        smoke_test._result("gui", True, "alive after 10s, no traceback"),
        smoke_test._result("cli", False, "did not exit within 10s (hung)"),
        smoke_test._result(
            "resources_about", None, "skipped: resource root could not be determined"
        ),
    ]


def test_report_prints_one_line_per_check_and_summary(capsys):
    for var in ("GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY"):
        os.environ.pop(var, None)
    exit_code = smoke_test.report(_sample_results())
    out = capsys.readouterr().out
    assert "PASS gui - alive after 10s, no traceback" in out
    assert "FAIL cli - did not exit within 10s (hung)" in out
    assert (
        "SKIP resources_about - skipped: resource root could not be determined" in out
    )
    assert "SUMMARY: 1 passed, 1 failed, 1 skipped (of 3)" in out
    assert exit_code == 1  # any FAIL -> non-zero exit


def test_report_without_github_env_vars_still_works(capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    results = [smoke_test._result("gui", True, "alive after 10s, no traceback")]
    exit_code = smoke_test.report(results)
    assert exit_code == 0
    assert "::error::" not in capsys.readouterr().out


def test_report_emits_error_annotations_when_github_actions(capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    smoke_test.report(_sample_results())
    out = capsys.readouterr().out
    assert "::error::cli did not exit within 10s (hung)" in out
    # Only FAILs are annotated, not PASS/SKIP.
    assert "::error::gui" not in out
    assert "::error::resources_about" not in out


def test_report_writes_markdown_table_to_step_summary(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    summary_file = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    smoke_test.report(_sample_results())
    content = summary_file.read_text(encoding="utf-8")
    assert "| Check | Status | Detail |" in content
    assert "| gui | PASS | alive after 10s, no traceback |" in content
    assert "| cli | FAIL | did not exit within 10s (hung) |" in content
    assert (
        "| resources_about | SKIP | skipped: resource root could not be determined |"
        in content
    )


# --------------------------------------------------------------------------
# Small pure-function helpers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stem, expected",
    [
        ("TiLiA-v0.6.4-windows", "0.6.4"),
        ("TiLiA-v0.6.4-macos-silicon", "0.6.4"),
        ("TiLiA-v0.6.4-some-branch-ubuntu", "0.6.4"),
        ("not-a-versioned-name", None),
    ],
)
def test_extract_version(stem, expected):
    assert smoke_test.extract_version(stem) == expected


def test_resolve_executable_appends_exe_suffix_when_needed(tmp_path):
    real = tmp_path / "TiLiA-v0.6.4-windows.exe"
    real.write_text("fake binary", encoding="utf-8")
    resolved = smoke_test.resolve_executable(tmp_path / "TiLiA-v0.6.4-windows")
    assert resolved == real


def test_resolve_executable_unwraps_macos_app_bundle(tmp_path):
    macos_dir = tmp_path / "tilia.app" / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)
    binary = macos_dir / "TiLiA-v0.6.4-macos-silicon"
    binary.write_text("fake binary", encoding="utf-8")
    binary.chmod(0o755)
    resolved = smoke_test.resolve_executable(tmp_path / "tilia.app")
    assert resolved == binary


def test_resolve_executable_uses_bundle_executable_from_info_plist(tmp_path):
    contents = tmp_path / "tilia.app" / "Contents"
    macos_dir = contents / "MacOS"
    macos_dir.mkdir(parents=True)
    for name in ("QtCore", "TiLiA-v0.6.4-macos-silicon", "QtGui"):
        (macos_dir / name).write_text("fake binary", encoding="utf-8")
        (macos_dir / name).chmod(0o755)
    with (contents / "Info.plist").open("wb") as f:
        plistlib.dump({"CFBundleExecutable": "TiLiA-v0.6.4-macos-silicon"}, f)
    resolved = smoke_test.resolve_executable(tmp_path / "tilia.app")
    assert resolved == macos_dir / "TiLiA-v0.6.4-macos-silicon"


def test_resolve_executable_ambiguous_bundle_without_info_plist_raises(tmp_path):
    macos_dir = tmp_path / "tilia.app" / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)
    for name in ("QtCore", "tilia"):
        (macos_dir / name).write_text("fake binary", encoding="utf-8")
        (macos_dir / name).chmod(0o755)
    with pytest.raises(FileNotFoundError):
        smoke_test.resolve_executable(tmp_path / "tilia.app")


def test_resolve_executable_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        smoke_test.resolve_executable(tmp_path / "nothing_here")


def test_resource_root_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke_test.platform, "system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = smoke_test.resource_root(
        tmp_path / "TiLiA-v0.6.4-windows.exe", "TiLiA", "0.6.4"
    )
    assert root == tmp_path / "TiLiA" / "v0.6.4"


def test_resource_root_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke_test.platform, "system", lambda: "Linux")
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(smoke_test.Path, "home", lambda: tmp_path)
    root = smoke_test.resource_root(tmp_path / "TiLiA-v0.6.4-ubuntu", "TiLiA", "0.6.4")
    assert root == tmp_path / ".cache" / "TiLiA" / "v0.6.4"


def test_resource_root_macos_app_bundle(tmp_path):
    macos_dir = tmp_path / "tilia.app" / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)
    root = smoke_test.resource_root(tmp_path / "tilia.app", "TiLiA", None)
    assert root == macos_dir


def test_resource_root_binary_inside_macos_app_bundle(tmp_path):
    macos_dir = tmp_path / "tilia.app" / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)
    root = smoke_test.resource_root(
        macos_dir / "TiLiA-v0.6.4-macos-silicon", "TiLiA", "0.6.4"
    )
    assert root == macos_dir


def test_resource_root_none_when_version_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke_test.platform, "system", lambda: "Linux")
    root = smoke_test.resource_root(tmp_path / "TiLiA-unversioned", "TiLiA", None)
    assert root is None


# --------------------------------------------------------------------------
# linux-clean-env profile: reusing check_gui/check_cli for the deploy job's
# clean-environment step
# --------------------------------------------------------------------------


def test_linux_clean_env_reuses_gui_and_cli_checks(tmp_path):
    gui_cmd = _write_fake_exe(
        tmp_path, "clean_env_gui.py", "import time\ntime.sleep(5)\n"
    )
    cli_cmd = _write_fake_exe(
        tmp_path,
        "clean_env_cli.py",
        """
        import sys
        print("invalid choice: 'cli'", file=sys.stderr)
        sys.exit(1)
        """,
    )
    gui_result = smoke_test.check_gui(
        gui_cmd, 0.3, name="linux_clean_env", log_path=tmp_path / "gui.log"
    )
    cli_result = smoke_test.check_cli(
        cli_cmd, 0.3, name="linux_clean_env", log_path=tmp_path / "cli.log"
    )
    assert gui_result.passed is True
    assert cli_result.passed is True
