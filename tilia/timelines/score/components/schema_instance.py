from __future__ import annotations

import math
from typing import Any

from tilia.timelines.base.component import TimelineComponent
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.score.schema import (
    VOICES,
    validate_degree,
    validate_schema,
)
from tilia.timelines.score.timeline import ScoreTimeline


def validate_placed_degree(value: Any, schema: dict) -> bool:
    """A degree placed on a notehead of the score.

    {"notehead": "<svg element id>", "stage": 0, "voice": "upper", "index": 0,
     "value": 6, "accidental": "="}

    Stage, voice and index say which of the schema's degrees it stands for.
    Value and accidental are kept with it, so a placement can differ from the
    definition (as an altered degree does in a real piece).
    """
    if not validate_degree(value) or value.get("voice") not in VOICES:
        return False
    notehead = value.get("notehead")
    if not isinstance(notehead, str) or not notehead:
        return False
    stage, index = value.get("stage"), value.get("index")
    if not all(isinstance(n, int) and not isinstance(n, bool) for n in (stage, index)):
        return False
    return 0 <= stage < len(schema["stages"]) and index >= 0


class SchemaInstance(TimelineComponent):
    """One occurrence of a schema in the score: the degrees placed on it.

    It has no time of its own. Where it is in the piece follows from the
    noteheads its degrees are placed on, as for score annotations.
    """

    SERIALIZABLE = ["schema", "degrees"]

    KIND = ComponentKind.SCHEMA_INSTANCE

    def __init__(
        self,
        timeline: ScoreTimeline,
        id: int,
        schema: dict,
        degrees: list[dict] | None = None,
        **_,
    ):
        self.validators = self.validators | {
            "schema": self.validate_schema,
            "degrees": self.validate_degrees,
        }
        self.schema = schema
        self.degrees = list(degrees or [])
        super().__init__(timeline, id)

    def __str__(self):
        return f"SchemaInstance({self.schema['name']}, {len(self.degrees)} degrees)"

    @property
    def ordinal(self) -> tuple[float, str]:
        # Score timelines sort all their kinds together, and the others start
        # with a time or an index: instances go after them, by id, so they
        # keep one order across undo and redo.
        return math.inf, self.id

    def validate_schema(self, value: Any) -> bool:
        return validate_schema(value) and all(
            validate_placed_degree(d, value) for d in self.degrees
        )

    def validate_degrees(self, value: Any) -> bool:
        return self.validate_degrees_for(value, self.schema)

    @staticmethod
    def validate_degrees_for(value: Any, schema: dict) -> bool:
        if not isinstance(value, list):
            return False
        if not all(validate_placed_degree(d, schema) for d in value):
            return False
        noteheads = [d["notehead"] for d in value]
        return len(noteheads) == len(set(noteheads))

    @property
    def color(self) -> str:
        return self.schema.get("color", "")

    @property
    def name(self) -> str:
        return self.schema["name"]
