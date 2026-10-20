"""Schema definitions: patterns of scale degrees, stage by stage.

A schema is a dict in the JSON format NoghenMadid uses, so that definitions
can move between the two applications:

    {
        "name": "Prinner",            # unique in a library
        "variant_of": "Prinner",      # family, may be ""
        "variant_short": "",          # short name within the family, may be ""
        "color": "#a7ffeb",
        "stages": [
            {
                "strength": "S",      # see STRENGTHS
                "upper": [{"value": 6, "accidental": "=", "voice": "upper"}],
                "inner": [],
                "lower": [{"value": 4, "accidental": "=", "voice": "lower"}],
            },
            ...
        ],
    }

Each degree may also have "relH", its register: see REGISTERS.

Schemas are plain data and are never changed in place: code that edits one
builds a new dict, as components keep them in their state.
"""

from __future__ import annotations

import copy
from typing import Any

from PySide6.QtGui import QColor

VOICES = ("upper", "inner", "lower")
STRENGTHS = {"S": "Strong", "W": "Weak", "G": "Neutral", "P": "Passing"}
ACCIDENTALS = {"=": "", "+": "↑", "-": "↓", "~": "♮"}
REGISTERS = {"": "Any register", "^": "High register", "V": "Low register"}
DEGREE_VALUES = range(1, 8)

DEFAULT_COLOR = "#a7ffeb"


def degree(value: int, voice: str, accidental: str = "=") -> dict[str, Any]:
    return {"value": value, "accidental": accidental, "voice": voice}


def degree_label(value: int, accidental: str = "=") -> str:
    """How a degree is written: its number, after an arrow if it's altered."""
    return f"{ACCIDENTALS.get(accidental, '')}{value}"


def validate_degree(value: Any, voice: str | None = None) -> bool:
    if not isinstance(value, dict):
        return False
    number = value.get("value")
    if isinstance(number, bool) or number not in DEGREE_VALUES:
        return False
    if value.get("accidental", "=") not in ACCIDENTALS:
        return False
    if value.get("relH", "") not in REGISTERS:
        return False
    if voice is not None and value.get("voice", voice) != voice:
        return False
    return True


def validate_stage(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("strength") not in STRENGTHS:
        return False
    for voice in VOICES:
        degrees = value.get(voice, [])
        if not isinstance(degrees, list):
            return False
        if not all(validate_degree(d, voice) for d in degrees):
            return False
    return any(value.get(voice) for voice in VOICES)


def validate_schema(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if not isinstance(value.get("name"), str) or not value["name"].strip():
        return False
    for attr in ("variant_of", "variant_short"):
        if not isinstance(value.get(attr, ""), str):
            return False
    if not QColor(value.get("color", DEFAULT_COLOR)).isValid():
        return False
    stages = value.get("stages")
    return (
        isinstance(stages, list)
        and len(stages) > 0
        and all(validate_stage(s) for s in stages)
    )


def stage_degree(schema: dict, stage: int, voice: str, index: int) -> dict | None:
    """The degree a schema has at a stage, voice and position, if any."""
    try:
        return schema["stages"][stage][voice][index]
    except (IndexError, KeyError, TypeError):
        return None


def family_name(schema: dict) -> str:
    return schema.get("variant_of", "").strip() or schema["name"]


def _schema(
    name: str,
    color: str,
    strengths: str,
    upper: list[int | str],
    lower: list[int | str],
    variant_of: str = "",
    variant_short: str = "",
) -> dict:
    """A two-voice schema, written as degree lists: "+4" is a raised 4."""

    def parse(text: int | str, voice: str) -> dict:
        text = str(text)
        accidental = text[0] if text[0] in ACCIDENTALS else "="
        return degree(int(text.lstrip("".join(ACCIDENTALS))), voice, accidental)

    return {
        "name": name,
        "variant_of": variant_of,
        "variant_short": variant_short,
        "color": color,
        "stages": [
            {
                "strength": strength,
                "upper": [parse(u, "upper")],
                "inner": [],
                "lower": [parse(b, "lower")],
            }
            for strength, u, b in zip(strengths, upper, lower, strict=True)
        ],
    }


# Starting points after Gjerdingen, Music in the Galant Style (2007), in the
# prototypical two-voice form, degrees relative to the main key. To be
# checked by a music theorist before shipping.
_STARTER_SCHEMATA = [
    _schema("Do-Re-Mi", "#ffd180", "SWS", [1, 2, 3], [1, 7, 1]),
    _schema("Fenaroli", "#b39ddb", "SWSW", [4, 3, 7, 1], [7, 1, 2, 3]),
    _schema("Fonte", "#80d8ff", "SWSW", [5, 4, 4, 3], ["+1", 2, 7, 1]),
    _schema("Meyer", "#ff8a80", "SWSW", [1, 7, 4, 3], [1, 2, 7, 1]),
    _schema("Monte", "#ccff90", "SWSW", ["-7", 6, 1, 7], [3, 4, "+4", 5]),
    _schema("Prinner", "#a7ffeb", "SWSW", [6, 5, 4, 3], [4, 3, 2, 1]),
    _schema("Quiescenza", "#f8bbd0", "WSWS", ["-7", 6, "+7", 1], [1, 1, 1, 1]),
    _schema(
        "Romanesca (stepwise)",
        "#fff59d",
        "SWSW",
        [1, 5, 1, 1],
        [1, 7, 6, 3],
        variant_of="Romanesca",
        variant_short="stepwise",
    ),
    _schema(
        "Romanesca (leaping)",
        "#fff176",
        "SWSW",
        [1, 5, 1, 1],
        [1, 5, 6, 3],
        variant_of="Romanesca",
        variant_short="leaping",
    ),
]


def starter_schemata() -> list[dict]:
    return copy.deepcopy(_STARTER_SCHEMATA)
