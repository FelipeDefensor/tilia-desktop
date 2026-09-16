import tilia.errors
from tests.utils import EXAMPLE_VIDEO_FILENAME, load_local_media
from tilia.timelines.audiowave.timeline import AudioWaveTimeline
from tilia.ui import commands


def test_undo_redo(audiowave_tlui, marker_tlui):

    # using marker tl to trigger an actions that can be undone
    commands.execute("timeline.marker.add")

    commands.execute("edit.undo")
    assert len(marker_tlui) == 0

    commands.execute("edit.redo")
    assert len(marker_tlui) == 1


class TestActions:
    def test_copy_paste(self, audiowave_tlui):
        audiowave_tlui.create_amplitudebar(0, 1, 1)
        audiowave_tlui.create_amplitudebar(1, 2, 0)

        audiowave_tlui.select_element(audiowave_tlui[0])
        commands.execute("timeline.component.copy")
        audiowave_tlui.deselect_element(0)

        audiowave_tlui.select_element(audiowave_tlui[1])
        commands.execute("timeline.component.paste")

        assert audiowave_tlui[1].get_data("start") != 0

    def test_delete(self, audiowave_tlui):
        audiowave_tlui.create_amplitudebar(0, 1, 1)

        audiowave_tlui.select_element(audiowave_tlui[0])
        commands.execute("timeline.component.delete")

        assert len(audiowave_tlui) == 1


class TestAddTimeline:
    def test_R103_add_with_local_video_loaded(
        self, tluis, tls, tilia_errors, resources
    ):
        """R103: adding an AudioWave timeline while a local video is loaded
        should warn (soundfile can't read the video container) and leave
        the timeline hidden, instead of crashing. Extracting audio from the
        video file to display it anyway is out of scope -- see release
        checklist notes for this row."""
        load_local_media((resources / EXAMPLE_VIDEO_FILENAME).resolve())

        commands.execute("timelines.add.audiowave", name="AudioWave")

        tilia_errors.assert_error()
        tilia_errors.assert_in_error_title(tilia.errors.AUDIOWAVE_INVALID_FILE.title)

        tl = tls.get_timeline_by_type(AudioWaveTimeline)
        assert tl is not None
        assert tl.get_data("is_visible") is False
