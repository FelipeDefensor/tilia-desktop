import pytest

from tilia.timelines.audiowave.timeline import AudioWaveTimeline


@pytest.fixture
def audiowave_cli(cli, tluis):
    """Brings up the UI (so commands are registered) and returns the cli."""
    yield cli


class TestAddAudioWaveTimeline:
    def test_add_audiowave_timeline(self, audiowave_cli, tls):
        audiowave_cli.parse_and_run("timelines add audiowave --name AW")
        tl = tls.get_timelines()[0]
        assert isinstance(tl, AudioWaveTimeline)
        assert tl.name == "AW"

    def test_add_audiowave_short_alias(self, audiowave_cli, tls):
        audiowave_cli.parse_and_run("timelines add aud --name AW")
        tl = tls.get_timelines()[0]
        assert isinstance(tl, AudioWaveTimeline)
        assert tl.name == "AW"

    def test_add_audiowave_with_explicit_height(self, audiowave_cli, tls):
        audiowave_cli.parse_and_run("timelines add audiowave --name AW --height 100")
        tl = tls.get_timelines()[0]
        assert tl.get_data("height") == 100


class TestRemoveAudioWaveTimeline:
    def test_remove_by_name(self, audiowave_cli, tls):
        audiowave_cli.parse_and_run("timelines add audiowave --name AW")
        assert len(tls) == 1
        audiowave_cli.parse_and_run("timelines remove name AW")
        assert not any(isinstance(t, AudioWaveTimeline) for t in tls.get_timelines())


class TestSaveLoadRoundTrip:
    def test_audiowave_round_trip(self, audiowave_cli, tls, tmp_path):
        save_path = str(tmp_path / "tla.tla")
        audiowave_cli.parse_and_run("timelines add audiowave --name AW")
        audiowave_cli.parse_and_run(f"save {save_path}")

        audiowave_cli.parse_and_run("clear --force")
        assert not any(isinstance(t, AudioWaveTimeline) for t in tls.get_timelines())

        audiowave_cli.parse_and_run(f"open {save_path}")
        loaded = [tl for tl in tls.get_timelines() if isinstance(tl, AudioWaveTimeline)]
        assert len(loaded) == 1
        assert loaded[0].name == "AW"
