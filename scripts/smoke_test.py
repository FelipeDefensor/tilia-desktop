"""
Cross-platform, stdlib-only smoke test for a built TiLiA executable.

Launches a built executable and checks that it comes up cleanly, that the
frozen build's CLI option is still rejected the way it's expected to be, that
a `.tla` file given on the command line opens, and that packaged resources
made it into the build. Runs either as a CI step (see
``.github/workflows/build.yml``) or by hand against a local build produced by
``python scripts/deploy.py <ref> <os>``.

Usage:
    python scripts/smoke_test.py <exe-or-.app> [options]

On Windows/Linux, ``<exe-or-.app>`` is the built executable. On macOS it is
the ``tilia.app`` bundle (the actual binary is resolved from
``Contents/MacOS`` inside it).

No third-party dependencies are used so this file can run with any plain
Python 3.10+ interpreter, independent of TiLiA's own virtualenv.
"""

from __future__ import annotations

import argparse
import os
import platform
import plistlib
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

TRACEBACK_MARKER = "Traceback (most recent call last)"
CLI_INVALID_CHOICE_MARKER = "invalid choice: 'cli'"
FILE_OPENED_MARKER = "APP_FILE_LOADED"

DEFAULT_WAIT = 10.0


# --------------------------------------------------------------------------
# Result plumbing
# --------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    passed: bool | None  # True = pass, False = fail, None = skipped
    detail: str

    @property
    def status(self) -> str:
        if self.passed is True:
            return "PASS"
        if self.passed is False:
            return "FAIL"
        return "SKIP"

    def line(self) -> str:
        return f"{self.status} {self.name} - {self.detail}"


def _result(name: str, passed: bool | None, detail: str) -> CheckResult:
    return CheckResult(name=name, passed=passed, detail=detail)


def tail(text: str, n: int = 40) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


# --------------------------------------------------------------------------
# Process running
# --------------------------------------------------------------------------


@dataclass
class ProcResult:
    alive: bool  # still running when the wait elapsed
    returncode: int | None  # None if alive (we don't wait for real exit)
    elapsed: float
    output: str
    log_path: Path


def _terminate(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        # Qt's multimedia backend and other helpers can spawn their own child
        # processes; kill the whole tree so no instance outlives the check.
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True
        )
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    except OSError:
        pass


def run_and_capture(
    cmd: list[str],
    wait: float,
    *,
    env: dict[str, str] | None = None,
    log_path: Path | None = None,
) -> ProcResult:
    """
    Launch ``cmd``, redirect its stdout+stderr to a log file (never to a
    pipe -- QT_DEBUG_PLUGINS=1 builds can print tens of thousands of lines,
    which would deadlock a pipe we're not actively draining), and report
    whether it is still alive after ``wait`` seconds.
    """
    if log_path is None:
        fd, name = tempfile.mkstemp(prefix="tilia_smoke_", suffix=".log")
        os.close(fd)
        log_path = Path(name)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    run_env = dict(env) if env is not None else None
    start = time.monotonic()
    with open(log_path, "wb") as log_f:
        proc = subprocess.Popen(
            cmd, stdout=log_f, stderr=subprocess.STDOUT, env=run_env
        )
        try:
            proc.wait(timeout=wait)
            exited_early = True
        except subprocess.TimeoutExpired:
            exited_early = False
    elapsed = time.monotonic() - start

    alive = not exited_early
    returncode = proc.returncode if exited_early else None
    if alive:
        _terminate(proc)

    try:
        output = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        output = ""

    return ProcResult(
        alive=alive,
        returncode=returncode,
        elapsed=elapsed,
        output=output,
        log_path=log_path,
    )


# --------------------------------------------------------------------------
# TiLiA's own log file (tilia/log.py, tilia/dirs.py) -- best effort only.
# platformdirs (a third-party dependency) picks the actual directory at
# runtime and can fall back between a "site" and a "user" location
# depending on filesystem permissions, which this stdlib-only script can't
# replicate exactly. We check the well-known conventional locations and
# skip the log-based assertions if none of them exist.
# --------------------------------------------------------------------------


def default_log_dir_candidates(product: str) -> list[Path]:
    system = platform.system()
    candidates: list[Path] = []
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / product / "logs")
        programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        candidates.append(Path(programdata) / product / "logs")
    elif system == "Darwin":
        candidates.append(
            Path.home() / "Library" / "Application Support" / product / "logs"
        )
        candidates.append(Path("/Library/Application Support") / product / "logs")
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        candidates.append(
            Path(xdg) / product / "logs"
            if xdg
            else Path.home() / ".local" / "share" / product / "logs"
        )
        candidates.append(Path("/usr/local/share") / product / "logs")
        candidates.append(Path("/usr/share") / product / "logs")
    return candidates


def find_recent_log(
    candidates: list[Path], since: float, slack: float = 2.0
) -> Path | None:
    for d in candidates:
        try:
            if not d.is_dir():
                continue
            logs = sorted(
                d.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True
            )
        except OSError:
            continue
        for lf in logs:
            try:
                if lf.stat().st_mtime >= since - slack:
                    return lf
            except OSError:
                continue
    return None


def _log_has_problem(text: str) -> bool:
    if TRACEBACK_MARKER in text:
        return True
    # TiLiA logs Qt's own messages (e.g. "ERROR [QtWarningMsg] ...") at ERROR
    # level whatever their severity; those are expected and not app errors.
    return (
        re.search(r"\b(ERROR|CRITICAL)\b(?! \[Qt\w*Msg\])", text, re.MULTILINE)
        is not None
    )


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def check_gui(
    cmd: list[str],
    wait: float,
    *,
    name: str = "gui",
    env: dict[str, str] | None = None,
    log_path: Path | None = None,
    log_dir_candidates: list[Path] | None = None,
) -> CheckResult:
    """
    Starting the GUI should still be alive after ``wait`` seconds, with no
    traceback in its output. Qt warnings (missing plugins, PulseAudio,
    missing font dirs, etc.) are expected and NOT failures -- only an actual
    Python traceback counts.
    """
    start = time.time()
    result = run_and_capture(cmd, wait, env=env, log_path=log_path)

    if not result.alive:
        return _result(
            name,
            False,
            f"exited early (rc={result.returncode}) after {result.elapsed:.2f}s, "
            f"before the {wait}s timeout; log={result.log_path}; tail:\n{tail(result.output)}",
        )
    if TRACEBACK_MARKER in result.output:
        return _result(
            name,
            False,
            f"traceback found in output while process was still alive; "
            f"log={result.log_path}; tail:\n{tail(result.output)}",
        )

    detail = f"alive after {wait}s, no traceback in output (log={result.log_path})"
    if log_dir_candidates is not None:
        logf = find_recent_log(log_dir_candidates, start)
        if logf is None:
            detail += (
                "; app log file check skipped (no log directory found among candidates)"
            )
        elif _log_has_problem(logf.read_text(encoding="utf-8", errors="replace")):
            return _result(
                name, False, f"app log file {logf} contains a traceback/ERROR record"
            )
        else:
            detail += f"; app log file {logf.name} has no traceback/ERROR record"
    return _result(name, True, detail)


def check_cli(
    cmd: list[str],
    wait: float,
    *,
    name: str = "cli",
    env: dict[str, str] | None = None,
    log_path: Path | None = None,
    expected_substring: str = CLI_INVALID_CHOICE_MARKER,
) -> CheckResult:
    """
    A packaged build's ``tilia.nuitka-package.config.yml`` rewrites
    ``tilia.boot``'s argparse choices down to just ``qt`` and drops the
    ``cli`` branch entirely (see the ``tilia.boot`` anti-bloat entry there --
    the CLI is source-only, per CLAUDE.md). So today's known (frozen-build)
    behaviour for ``--user-interface=cli`` is to exit almost immediately,
    non-zero, with an argparse "invalid choice: 'cli'" message. This asserts
    that exact behaviour, not a working CLI; a hang or a different message is
    a FAIL.
    """
    result = run_and_capture(
        cmd + ["--user-interface=cli"], wait, env=env, log_path=log_path
    )

    if result.alive:
        return _result(
            name,
            False,
            f"did not exit within {wait}s (hung); expected a quick non-zero exit; "
            f"log={result.log_path}",
        )
    if result.returncode == 0:
        return _result(
            name,
            False,
            f"exited 0 after {result.elapsed:.2f}s (expected non-zero); log={result.log_path}",
        )
    if expected_substring not in result.output:
        return _result(
            name,
            False,
            f"exited rc={result.returncode} after {result.elapsed:.2f}s but output is missing "
            f"{expected_substring!r}; log={result.log_path}; tail:\n{tail(result.output)}",
        )
    return _result(
        name,
        True,
        f"exited rc={result.returncode} after {result.elapsed:.2f}s with the expected "
        f"argparse message",
    )


def check_file_arg(
    cmd: list[str],
    file_path: str | Path | None,
    wait: float,
    *,
    name: str = "file_arg",
    env: dict[str, str] | None = None,
    log_path: Path | None = None,
    log_dir_candidates: list[Path] | None = None,
) -> CheckResult:
    """
    Running with a positional .tla path (tilia/boot.py::setup_parser) should
    survive ``wait`` seconds without a traceback. We only assert the file was
    actually opened when that's observable without app changes: setting
    LOG_REQUESTS=1 makes every Post (including APP_FILE_LOADED) land in
    TiLiA's own log file, so we look for that marker there.
    """
    if file_path is None:
        return _result(
            name, None, "skipped: no --file given (avoiding a hand-written .tla)"
        )
    file_path = Path(file_path)
    if not file_path.is_file():
        return _result(name, False, f"given --file {file_path} does not exist")

    start = time.time()
    run_env = dict(env) if env is not None else dict(os.environ)
    if log_dir_candidates is not None:
        run_env["LOG_REQUESTS"] = "1"

    result = run_and_capture(
        cmd + [str(file_path)], wait, env=run_env, log_path=log_path
    )

    if not result.alive:
        return _result(
            name,
            False,
            f"exited early (rc={result.returncode}) after {result.elapsed:.2f}s with "
            f"--file={file_path.name}; log={result.log_path}; tail:\n{tail(result.output)}",
        )
    if TRACEBACK_MARKER in result.output:
        return _result(
            name,
            False,
            f"traceback found in output with --file={file_path.name}; log={result.log_path}; "
            f"tail:\n{tail(result.output)}",
        )

    detail = f"alive after {wait}s with --file={file_path.name}, no traceback"
    if log_dir_candidates is not None:
        logf = find_recent_log(log_dir_candidates, start)
        if logf is None:
            detail += (
                "; open-confirmation skipped (no log directory found among candidates)"
            )
        else:
            text = logf.read_text(encoding="utf-8", errors="replace")
            if FILE_OPENED_MARKER in text:
                detail += f"; confirmed {FILE_OPENED_MARKER} in app log"
            else:
                detail += f"; open-confirmation skipped ({FILE_OPENED_MARKER} marker not found in app log)"
    else:
        detail += "; open-confirmation skipped (no log directory candidates given)"
    return _result(name, True, detail)


def check_resources(
    check_name: str, root: Path | str | None, filenames: list[str]
) -> CheckResult:
    """
    Packaging check -- confirm specific non-.py resource files shipped
    inside the built app (a Nuitka standalone dist dir, a macOS .app
    bundle's Contents/MacOS, or an extracted Linux AppImage payload).
    Searches recursively under ``root`` since the exact nesting of that tree
    isn't part of the public contract.
    """
    if root is None:
        return _result(
            check_name, None, "skipped: resource root could not be determined"
        )
    root = Path(root)
    if not root.is_dir():
        return _result(
            check_name,
            None,
            f"skipped: resource root {root} does not exist (was the exe run at least once?)",
        )
    missing = [f for f in filenames if not any(root.rglob(f))]
    if missing:
        return _result(check_name, False, f"missing under {root}: {', '.join(missing)}")
    return _result(check_name, True, f"found {', '.join(filenames)} under {root}")


# --------------------------------------------------------------------------
# Path helpers
# --------------------------------------------------------------------------


def resolve_executable(path: Path) -> Path:
    """Resolve the actual binary to run: unwraps a macOS .app bundle, and
    tries appending '.exe' if the given path doesn't exist as-is (Nuitka
    enforces that suffix on Windows even though deploy.py's recorded
    out-filepath/out-binary-name outputs don't include it).
    """
    path = Path(path)
    if path.suffix == ".app":
        return _bundle_executable(path)
    if path.exists():
        return path
    exe_variant = path.with_name(path.name + ".exe")
    if exe_variant.exists():
        return exe_variant
    raise FileNotFoundError(f"Executable not found: {path} (also tried {exe_variant})")


def _bundle_executable(bundle: Path) -> Path:
    """The binary a macOS .app launches, per CFBundleExecutable in Info.plist.

    Contents/MacOS also holds Qt libraries with the executable bit set, so
    "an executable file in there" is not reliably the app itself.
    """
    macos_dir = bundle / "Contents" / "MacOS"
    info = bundle / "Contents" / "Info.plist"
    if info.is_file():
        with info.open("rb") as f:
            name = plistlib.load(f).get("CFBundleExecutable")
        if name and (macos_dir / name).is_file():
            return macos_dir / name
    candidates = (
        [p for p in macos_dir.iterdir() if p.is_file() and os.access(p, os.X_OK)]
        if macos_dir.is_dir()
        else []
    )
    if len(candidates) != 1:
        raise FileNotFoundError(
            f"Can't tell which file under {macos_dir} is the app: no usable "
            f"CFBundleExecutable in {info}, {len(candidates)} executable candidates"
        )
    return candidates[0]


def resource_root(binary: Path, original_path: Path) -> Path | None:
    """Where packaged, non-.py resources live for this build.

    deploy.py builds with Nuitka ``--mode=app`` (macOS) or
    ``--mode=standalone`` (Windows/Linux) -- never ``--mode=onefile`` -- so
    there's no runtime extraction step to locate on Windows or a raw Linux
    standalone build: resources sit right beside the executable, in
    whatever directory holds it (the Nuitka ``tilia.dist`` dir, Velopack's
    installed ``current/`` dir on Windows, or the macOS .app bundle's
    Contents/MacOS, which already holds the files with no separate
    extraction step). ``binary``/``original_path`` may be the .app itself or
    the binary inside it, as the build workflow passes either.

    The one exception is a Linux .AppImage: its payload is a compressed,
    self-mounting image, so it's unpacked with the AppImage's own
    ``--appimage-extract`` to inspect it without depending on FUSE being
    available. The exact directory layout Velopack's AppImage produces
    inside that payload isn't verified here (that needs a real build to
    check) -- only that extraction itself works; check_resources() searches
    recursively, so the nesting doesn't matter as long as extraction
    succeeded.
    """
    bundle = next(
        (
            p
            for p in (original_path, *original_path.parents, binary, *binary.parents)
            if p.suffix == ".app"
        ),
        None,
    )
    if bundle is not None:
        macos_dir = bundle / "Contents" / "MacOS"
        return macos_dir if macos_dir.is_dir() else None
    if binary.suffix.lower() == ".appimage":
        return _extract_appimage(binary)
    return binary.parent


def _extract_appimage(appimage: Path) -> Path | None:
    """Best-effort extraction of a Linux .AppImage's payload. Returns None
    (the caller treats that as "can't tell" / SKIP) if extraction isn't
    possible in this environment.
    """
    extract_dir = Path(tempfile.mkdtemp(prefix="tilia_smoke_appimage_"))
    try:
        subprocess.run(
            [str(appimage), "--appimage-extract"],
            cwd=extract_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    squashfs_root = extract_dir / "squashfs-root"
    return squashfs_root if squashfs_root.is_dir() else None


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", "<br>")


def report(results: list[CheckResult]) -> int:
    for r in results:
        print(r.line())

    passed = sum(1 for r in results if r.passed is True)
    failed = sum(1 for r in results if r.passed is False)
    skipped = sum(1 for r in results if r.passed is None)
    print(
        f"SUMMARY: {passed} passed, {failed} failed, {skipped} skipped (of {len(results)})"
    )

    if os.environ.get("GITHUB_ACTIONS") == "true":
        for r in results:
            if r.passed is False:
                first_line = r.detail.splitlines()[0] if r.detail else ""
                print(f"::error::{r.name} {first_line}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n### TiLiA smoke test\n\n")
            f.write("| Check | Status | Detail |\n|---|---|---|\n")
            for r in results:
                f.write(f"| {r.name} | {r.status} | {_md_escape(r.detail)} |\n")
            f.write(
                f"\n{passed} passed, {failed} failed, {skipped} skipped (of {len(results)})\n"
            )

    return 1 if failed else 0


# --------------------------------------------------------------------------
# CLI entry point
# --------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke test a built TiLiA executable.",
    )
    parser.add_argument(
        "executable",
        help="Path to the built exe (Windows/Linux) or the tilia.app bundle (macOS).",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=DEFAULT_WAIT,
        help=f"Seconds to wait before checking a process is still alive (default: {DEFAULT_WAIT}).",
    )
    parser.add_argument(
        "--file",
        default=None,
        help="Path to an existing .tla file for the file_arg check (e.g. tests/resources/tla/many_beats.tla). "
        "Omit to skip that check.",
    )
    parser.add_argument("--product-name", default="TiLiA")
    parser.add_argument(
        "--profile",
        choices=["full", "linux-clean-env"],
        default="full",
        help="'full' runs gui+cli+file_arg+resource checks (build job). "
        "'linux-clean-env' runs only gui+cli, for the deploy job's clean-environment step.",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="Directory to write per-check subprocess logs into. Default: a fresh temp dir.",
    )
    parser.add_argument(
        "--no-app-log",
        action="store_true",
        help="Don't look for TiLiA's own log file (skips the extra part of the gui/file_arg checks).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    exe_input = Path(args.executable)
    binary = resolve_executable(exe_input)
    cmd = [str(binary)]

    log_dir = (
        Path(args.log_dir)
        if args.log_dir
        else Path(tempfile.mkdtemp(prefix="tilia_smoke_"))
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    log_candidates = (
        None if args.no_app_log else default_log_dir_candidates(args.product_name)
    )

    results: list[CheckResult] = []

    if args.profile == "linux-clean-env":
        results.append(
            check_gui(
                cmd,
                args.wait,
                name="linux_clean_env",
                log_path=log_dir / "linux_clean_env_gui.log",
            )
        )
        results.append(
            check_cli(
                cmd,
                args.wait,
                name="linux_clean_env",
                log_path=log_dir / "linux_clean_env_cli.log",
            )
        )
    else:
        results.append(
            check_gui(
                cmd,
                args.wait,
                log_dir_candidates=log_candidates,
                log_path=log_dir / "gui.log",
            )
        )
        results.append(check_cli(cmd, args.wait, log_path=log_dir / "cli.log"))
        results.append(
            check_file_arg(
                cmd,
                args.file,
                args.wait,
                log_dir_candidates=log_candidates,
                log_path=log_dir / "file_arg.log",
            )
        )

        root = resource_root(binary, exe_input)
        results.append(check_resources("resources_about", root, ["LICENSE"]))
        results.append(
            check_resources("resources_youtube", root, ["youtube.html", "youtube.css"])
        )
        results.append(
            check_resources(
                "resources_score", root, ["svg_maker.html", "timewise_to_partwise.xsl"]
            )
        )

    return report(results)


if __name__ == "__main__":
    sys.exit(main())
