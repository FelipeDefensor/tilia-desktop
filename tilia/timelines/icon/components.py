from __future__ import annotations

from typing import TYPE_CHECKING

from tilia.timelines.base.validators import (
    validate_time,
    validate_color,
    validate_string,
)
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.icon.enums import Alignment
from tilia.timelines.icon.validators import validate_alignment

if TYPE_CHECKING:
    from tilia.timelines.marker.timeline import ContourTimeline

from tilia.timelines.base.component import TimelineComponent


class Icon(TimelineComponent):
    ICON_NAMES = [
        "DashLow",
        "DashMid",
        "DashHigh",
        "DotLow",
        "DotMid",
        "DotHigh",
        "Cross"
    ]

    SERIALIZABLE_BY_VALUE = ["time", "icon_name", "h_alignment"]
    SERIALIZABLE_BY_ID = []
    SERIALIZABLE_BY_ID_LIST = []
    ORDERING_ATTRS = ("time",)

    KIND = ComponentKind.ICON

    validators = {
        "timeline": lambda _: False,
        "id": lambda _: False,
        "time": validate_time,
        "h_alignment": validate_alignment,
    }

    def __init__(
        self,
        timeline: ContourTimeline,
        id: int,
        time: float,
        icon_name: str,
        h_alignment: Alignment,
        **_,
    ):
        super().__init__(timeline, id)

        self.validators = self.validators | {"icon_name": self._validate_icon_name}

        print(type(h_alignment))
        self.time = time
        self.icon_name = icon_name
        self.h_alignment = h_alignment if isinstance(h_alignment, Alignment) else Alignment(h_alignment)

    def _validate_icon_name(self, value: str) -> bool:
        return value in self.ICON_NAMES

    def __str__(self):
        return f"Icon({self.time, self.icon_name})"

    def __repr__(self):
        return str(dict(self.__dict__.items()))
