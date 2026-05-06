from unittest import mock

import pytest


class TestCLI:
    def test_wrong_argument(self, cli, tilia_errors):
        cli.parse_and_run("nonsense")

        tilia_errors.assert_error()
        tilia_errors.assert_in_error_message("nonsense")

    PARSE_COMMAND_CASES = [
        ("spaced args", ["spaced", "args"]),
        ('"spaced args"', ["spaced args"]),
        ('"spaced args" and more', ["spaced args", "and", "more"]),
        ('"three spaced args"', ["three spaced args"]),
        ('"three spaced args" and more', ["three spaced args", "and", "more"]),
        (
            'surrounded "quoted args" surrounded',
            ["surrounded", "quoted args", "surrounded"],
        ),
        ('"unfinished', None),
        ('"unfinished and more', None),
        ('not started"', None),
        ('notstarted"', None),
        ('notstarted" and more', None),
        ('this has notstarted"', None),
        ('"onestring"', ["onestring"]),
        ("trailing space ", ["trailing", "space"]),
        ("trailing spaces     ", ["trailing", "spaces"]),
    ]

    @pytest.mark.parametrize("command,result", PARSE_COMMAND_CASES)
    def test_parse_command(self, cli, command, result):

        assert cli.parse_command(command) == result

    @pytest.mark.parametrize("command", ["quit", "exit", "q"])
    def test_quit_command_stops_loop(self, cli, command):
        cli._is_running = True
        cli.parse_and_run(command)
        assert not cli._is_running

    def test_launch_eof_sets_is_running_false(self, cli):
        with mock.patch("builtins.input", side_effect=EOFError):
            with pytest.raises(SystemExit):
                cli.launch()
        assert not cli._is_running


class TestYTDLPAcknowledgement:
    """The CLI must serve Get.FROM_USER_YT_DLP_ACKNOWLEDGEMENT so users
    running headless / via the CLI also get a chance to opt in or out
    of yt-dlp downloads (instead of getting silent "no waveform")."""

    def test_yes_yes_persists_dont_show_again(self, cli):
        from tilia.requests import Get, get

        with mock.patch("tilia.ui.cli.ui.ask_yes_or_no", side_effect=[True, True]):
            assert get(Get.FROM_USER_YT_DLP_ACKNOWLEDGEMENT) == (True, True)

    def test_yes_no_does_not_persist(self, cli):
        from tilia.requests import Get, get

        with mock.patch("tilia.ui.cli.ui.ask_yes_or_no", side_effect=[True, False]):
            assert get(Get.FROM_USER_YT_DLP_ACKNOWLEDGEMENT) == (True, False)

    def test_no_returns_false(self, cli):
        from tilia.requests import Get, get

        # ``ask_yes_or_no`` only fires once — we never reach the second
        # prompt when the user declines the disclaimer.
        with mock.patch("tilia.ui.cli.ui.ask_yes_or_no", return_value=False) as m:
            assert get(Get.FROM_USER_YT_DLP_ACKNOWLEDGEMENT) == (False, False)
        assert m.call_count == 1
