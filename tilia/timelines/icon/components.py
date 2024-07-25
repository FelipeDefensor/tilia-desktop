from __future__ import annotations

from typing import TYPE_CHECKING

from tilia.timelines.base.validators import (
    validate_time,
    validate_color,
    validate_string,
)
from tilia.timelines.component_kinds import ComponentKind

if TYPE_CHECKING:
    from tilia.timelines.marker.timeline import ContourTimeline

from tilia.timelines.base.component import TimelineComponent


class Icon(TimelineComponent):
    SERIALIZABLE_BY_VALUE = ["time", "path"]
    SERIALIZABLE_BY_ID = []
    SERIALIZABLE_BY_ID_LIST = []
    ORDERING_ATTRS = ("time", "level")

    KIND = ComponentKind.MARKER

    validators = {
        "timeline": lambda _: False,
        "id": lambda _: False,
        "time": validate_time,
        "path": validate_path,
    }

    def __init__(
        self,
        timeline: ContourTimeline,
        id: int,
        start: float,
        end: float,
        level: int,
        label="",
        color=None,
        comments="",
        **_,
    ):
        super().__init__(timeline, id)

        self.validators = self.validators | {"level", self._validate_level}

        self.start = start
        self.end = end
        self.level = level
        self.label = label
        self.color = color
        self.comments = comments

    def _validate_level(self, value):
        return 0 < value < self.timeline.level_count

    def __str__(self):
        return f"ContourUnit({self.start, self.end, self.level})"

    def __repr__(self):
        return str(dict(self.__dict__.items()))
