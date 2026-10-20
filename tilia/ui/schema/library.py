"""The schemata the user can annotate with: the starter set, plus their own.

A custom schema with a starter's name replaces it. Removing that custom
schema brings the starter back.
"""

from __future__ import annotations

import copy

from tilia.requests import Post, post
from tilia.settings import settings
from tilia.timelines.score.schema import (
    family_name,
    starter_schemata,
    validate_schema,
)


def _custom() -> list[dict]:
    return [s for s in settings.get_custom_schemata() if validate_schema(s)]


def get_schemata() -> list[dict]:
    """All schemata, by family and then by name."""
    by_name = {s["name"]: s for s in starter_schemata()}
    for schema in _custom():
        by_name[schema["name"]] = schema
    return sorted(by_name.values(), key=lambda s: (family_name(s), s["name"]))


def get_schema(name: str) -> dict | None:
    for schema in get_schemata():
        if schema["name"] == name:
            return copy.deepcopy(schema)
    return None


def is_custom(name: str) -> bool:
    return any(s["name"] == name for s in _custom())


def is_starter(name: str) -> bool:
    return any(s["name"] == name for s in starter_schemata())


def save_schema(schema: dict, replaces: str | None = None) -> None:
    """Saves a custom schema. `replaces` is the name it had before, when the
    user renamed it: that one is removed."""
    if not validate_schema(schema):
        raise ValueError(f"Invalid schema: {schema}")
    names_to_drop = {schema["name"], replaces}
    custom = [s for s in _custom() if s["name"] not in names_to_drop]
    settings.set_custom_schemata(custom + [copy.deepcopy(schema)])
    post(Post.SCHEMA_LIBRARY_UPDATED)


def delete_schema(name: str) -> None:
    settings.set_custom_schemata([s for s in _custom() if s["name"] != name])
    post(Post.SCHEMA_LIBRARY_UPDATED)
