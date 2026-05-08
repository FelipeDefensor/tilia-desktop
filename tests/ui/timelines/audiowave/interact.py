from PySide6.QtCore import Qt

from tilia.ui.coords import time_x_converter

NoModifier = Qt.KeyboardModifier.NoModifier


def click_at_time(audiowave_tlui, time, modifier=NoModifier, double=False):
    """Click on the waveform at the scene-x corresponding to `time` seconds.

    The audiowave timeline routes click handling through the timeline UI,
    not the element body — `on_left_click(item, modifier, double, x, y)`
    seeks playback if `item` is the element body.
    """
    body = audiowave_tlui[0].body if len(audiowave_tlui) else None
    x = int(time_x_converter.get_x_by_time(time))
    audiowave_tlui.on_left_click(body, modifier, double, x, 0)
