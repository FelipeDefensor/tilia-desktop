from __future__ import annotations

from tilia.ui.actions import TiliaAction
from tilia.ui.timelines.toolbar import TimelineToolbar


class IconTimelineToolbar(TimelineToolbar):
    ACTIONS = [TiliaAction.ICON_ADD]
