"""
Tests for scripts/smoke_test.py.

The script under test is a standalone, stdlib-only file (not part of the
`tilia` package), so it's loaded here by adding `scripts/` to `sys.path`
rather than by installing it. Every process-based check is exercised
against tiny fake "executables" -- Python scripts run via `sys.executable`
-- instead of a real TiLiA build, so these tests are fast and don't need a
Nuitka build.

A fake that should stay alive is watched for well under a second. A fake
that should exit gets WAIT_FOR_EXIT: the checks return as soon as it exits,
so the long wait costs nothing, and a loaded machine can take more than a
fraction of a second just to start Python.
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

WAIT_FOR_EXIT = 30.0


def _write_fake_exe(tmp_path: Path, name: str, body: str) -> list[str]:
    script = tmp_path / name
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(script)]


# --------------------------------------------------------------------------
# check_gui
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "log, has_problem",
    [
        ("2026-09-26 19:10:25,657 ERROR [QtInfoMsg] None:0 - Using FFmpeg", False),
        ("2026-09-26 19:10:26,371 ERROR [QtWarningMsg] None:0 - No hints", False),
        ("2026-09-26 19:10:26,368 INFO TIMELINE_CREATE_DONE", False),
        ("2026-09-26 19:10:27,000 ERROR Could not load media", True),
        ("2026-09-26 19:10:27,000 CRITICAL Unhandled exception", True),
        ("Traceback (most recent call last):\n  File ...", True),
    ],
    ids=["qt-info", "qt-warning", "info", "app-error", "critical", "traceback"],
)
def test_app_log_problems_ignore_qt_messages(log, has_problem):
    assert smoke_test._log_has_problem(log) is has_problem


def test_check_gui_healthy_process_passes(tmp_path):
    cmd = _write_fake_exe(tmp_path, "gui_healthy.py", "import time\ntime.sleep(5)\n")
    result = smoke_test.check_gui(cmd, 0.3, log_path=tmp_path / "out.log")
    assert result.passed is True


def test_check_gui_early_exit_fails(tmp_path):
    cmd = _write_fake_exe(tmp_path, "gui_early_exit.py", "import sys\nsys.exit(0)\n")
    result = smoke_test.check_gui(cmd, WAIT_FOR_EXIT, log_path=tmp_path / "out.log")
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
    # Long enough for the fake to start and print, well before it stops sleeping.
    result = smoke_test.check_gui(cmd, 2, log_path=tmp_path / "out.log")
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
    result = smoke_test.check_cli(cmd, WAIT_FOR_EXIT, log_path=tmp_path / "out.log")
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
    result = smoke_test.check_cli(cmd, WAIT_FOR_EXIT, log_path=tmp_path / "out.log")
    assert result.passed is False
    assert "missing" in result.detail


def test_check_cli_exit_zero_fails(tmp_path):
    cmd = _write_fake_exe(tmp_path, "cli_exit_zero.py", "import sys\nsys.exit(0)\n")
    result = smoke_test.check_cli(cmd, WAIT_FOR_EXIT, log_path=tmp_path / "out.log")
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


def test_resolve_executable_appends_exe_suffix_when_needed(tmp_path):
    real = tmp_path / "TiLiA.exe"
    real.write_text("fake binary", encoding="utf-8")
    resolved = smoke_test.resolve_executable(tmp_path / "TiLiA")
    assert resolved == real


def test_resolve_executable_unwraps_macos_app_bundle(tmp_path):
    macos_dir = tmp_path / "tilia.app" / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)
    binary = macos_dir / "TiLiA-bin"
    binary.write_text("fake binary", encoding="utf-8")
    binary.chmod(0o755)
    resolved = smoke_test.resolve_executable(tmp_path / "tilia.app")
    assert resolved == binary


def test_resolve_executable_uses_bundle_executable_from_info_plist(tmp_path):
    contents = tmp_path / "tilia.app" / "Contents"
    macos_dir = contents / "MacOS"
    macos_dir.mkdir(parents=True)
    for name in ("QtCore", "TiLiA-bin", "QtGui"):
        (macos_dir / name).write_text("fake binary", encoding="utf-8")
        (macos_dir / name).chmod(0o755)
    with (contents / "Info.plist").open("wb") as f:
        plistlib.dump({"CFBundleExecutable": "TiLiA-bin"}, f)
    resolved = smoke_test.resolve_executable(tmp_path / "tilia.app")
    assert resolved == macos_dir / "TiLiA-bin"


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


# --------------------------------------------------------------------------
# resource_root -- Nuitka standalone/app builds (no onefile runtime
# extraction): resources sit right beside the resolved binary, except a
# macOS .app bundle (Contents/MacOS) and a Linux .AppImage (extracted).
# --------------------------------------------------------------------------


def test_resource_root_windows_standalone_dir_is_binarys_parent(tmp_path):
    dist_dir = tmp_path / "tilia.dist"
    dist_dir.mkdir()
    binary = dist_dir / "TiLiA.exe"
    binary.write_text("fake binary", encoding="utf-8")
    root = smoke_test.resource_root(binary, binary)
    assert root == dist_dir


def test_resource_root_linux_standalone_dir_is_binarys_parent(tmp_path):
    dist_dir = tmp_path / "tilia.dist"
    dist_dir.mkdir()
    binary = dist_dir / "TiLiA"
    binary.write_text("fake binary", encoding="utf-8")
    root = smoke_test.resource_root(binary, binary)
    assert root == dist_dir


def test_resource_root_macos_app_bundle(tmp_path):
    macos_dir = tmp_path / "tilia.app" / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)
    binary = macos_dir / "TiLiA-bin"
    binary.write_text("fake binary", encoding="utf-8")
    root = smoke_test.resource_root(binary, tmp_path / "tilia.app")
    assert root == macos_dir


def test_resource_root_macos_uses_bundle_ancestor_of_binary_when_no_app_original(
    tmp_path,
):
    macos_dir = tmp_path / "tilia.app" / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)
    binary = macos_dir / "TiLiA-bin"
    binary.write_text("fake binary", encoding="utf-8")
    # original_path is already the resolved binary (no .app in it), so the
    # bundle has to be found by walking the binary's own ancestors instead.
    root = smoke_test.resource_root(binary, binary)
    assert root == macos_dir


@pytest.mark.skipif(
    os.name == "nt", reason="AppImage extraction is a Linux-only mechanism"
)
def test_resource_root_appimage_extracts_via_appimage_extract_flag(tmp_path):
    fake_appimage = tmp_path / "TiLiA-ubuntu.AppImage"
    fake_appimage.write_text(
        textwrap.dedent(
            """
            #!/bin/sh
            if [ "$1" = "--appimage-extract" ]; then
                mkdir -p squashfs-root/usr/bin
                echo GPL > squashfs-root/usr/bin/LICENSE
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_appimage.chmod(0o755)
    root = smoke_test.resource_root(fake_appimage, fake_appimage)
    assert root is not None
    assert root.name == "squashfs-root"
    assert any(root.rglob("LICENSE"))


def test_resource_root_appimage_extraction_failure_is_skipped(tmp_path, monkeypatch):
    fake_appimage = tmp_path / "TiLiA-ubuntu.AppImage"
    fake_appimage.write_text("not actually runnable", encoding="utf-8")
    # Don't rely on chmod +x / a real shell: force the subprocess call itself
    # to fail so this exercises the "extraction not possible here" path.
    monkeypatch.setattr(
        smoke_test.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(OSError("no interpreter")),
    )
    root = smoke_test.resource_root(fake_appimage, fake_appimage)
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
        cli_cmd, WAIT_FOR_EXIT, name="linux_clean_env", log_path=tmp_path / "cli.log"
    )
    assert gui_result.passed is True
    assert cli_result.passed is True
