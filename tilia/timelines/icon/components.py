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
    ICON_NAMES = [
        'dash',
        'dot',
        'cross'
    ]
    SERIALIZABLE_BY_VALUE = ["time", "path"]
    SERIALIZABLE_BY_ID = []
    SERIALIZABLE_BY_ID_LIST = []
    ORDERING_ATTRS = ("time", "level")

    KIND = ComponentKind.MARKER

    validators = {
        "timeline": lambda _: False,
        "id": lambda _: False,
        "time": validate_time,
    }

    def __init__(
        self,
        timeline: ContourTimeline,
        id: int,
        time: float,
        icon_name: str,
        **_,
    ):
        super().__init__(timeline, id)

        self.validators = self.validators | {"icon_name": self._validate_icon_name}

        self.time = time
        self.icon_name = icon_name

    def _validate_icon_name(self, value: str) -> bool:
        return value in self.ICON_NAMES

    def __str__(self):
        return f"ContourUnit({self.start, self.end, self.level})"

    def __repr__(self):
        return str(dict(self.__dict__.items()))
