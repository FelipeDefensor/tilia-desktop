import copy

import pytest

from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.score.schema import (
    degree,
    degree_label,
    family_name,
    stage_degree,
    starter_schemata,
    validate_schema,
)


def prinner():
    return next(s for s in starter_schemata() if s["name"] == "Prinner")


def placed(notehead="n0", stage=0, voice="upper", index=0, value=6):
    return {
        "notehead": notehead,
        "stage": stage,
        "voice": voice,
        "index": index,
        "value": value,
        "accidental": "=",
    }


class TestSchemaDefinitions:
    def test_starters_are_valid(self):
        assert all(validate_schema(s) for s in starter_schemata())

    def test_starter_names_are_unique(self):
        names = [s["name"] for s in starter_schemata()]
        assert len(names) == len(set(names))

    def test_starters_are_copies(self):
        starter_schemata()[0]["name"] = "changed"
        assert starter_schemata()[0]["name"] != "changed"

    def test_prinner(self):
        stages = prinner()["stages"]
        assert [s["upper"][0]["value"] for s in stages] == [6, 5, 4, 3]
        assert [s["lower"][0]["value"] for s in stages] == [4, 3, 2, 1]

    def test_altered_degree(self):
        fonte = next(s for s in starter_schemata() if s["name"] == "Fonte")
        assert fonte["stages"][0]["lower"][0] == degree(1, "lower", "+")

    @pytest.mark.parametrize(
        "change",
        [
            lambda s: s.update(name=""),
            lambda s: s.update(name=3),
            lambda s: s.update(color="not a color"),
            lambda s: s.update(stages=[]),
            lambda s: s["stages"][0].update(strength="X"),
            lambda s: s["stages"][0].update(upper=[], inner=[], lower=[]),
            lambda s: s["stages"][0]["upper"][0].update(value=8),
            lambda s: s["stages"][0]["upper"][0].update(value=True),
            lambda s: s["stages"][0]["upper"][0].update(accidental="#"),
            lambda s: s["stages"][0]["upper"][0].update(relH="up"),
            lambda s: s["stages"][0]["upper"][0].update(voice="lower"),
            lambda s: s.update(variant_of=None),
        ],
    )
    def test_invalid(self, change):
        schema = prinner()
        change(schema)
        assert not validate_schema(schema)

    def test_register_is_optional(self):
        schema = prinner()
        schema["stages"][0]["upper"][0]["relH"] = "^"
        assert validate_schema(schema)

    def test_noghenmadid_format(self):
        # As NoghenMadid saves a schema (its default new one).
        schema = {
            "name": "My Schemata",
            "variant_short": "My Schemata",
            "color": "#a7ffeb",
            "stages": [
                {
                    "strength": "S",
                    "lower": [{"value": 1, "accidental": "=", "voice": "lower"}],
                    "inner": [],
                    "upper": [{"value": 1, "accidental": "=", "voice": "upper"}],
                }
            ],
        }
        assert validate_schema(schema)
        assert family_name(schema) == "My Schemata"

    def test_stage_degree(self):
        assert stage_degree(prinner(), 3, "lower", 0)["value"] == 1
        assert stage_degree(prinner(), 4, "lower", 0) is None
        assert stage_degree(prinner(), 0, "inner", 0) is None

    def test_degree_label(self):
        assert degree_label(4) == "4"
        assert degree_label(4, "+") == "↑4"
        assert degree_label(7, "-") == "↓7"


class TestSchemaInstance:
    def test_create(self, score_tl):
        instance, _ = score_tl.create_component(
            ComponentKind.SCHEMA_INSTANCE, schema=prinner(), degrees=[placed()]
        )
        assert instance.name == "Prinner"
        assert instance.color == "#a7ffeb"

    def test_create_with_invalid_schema_fails(self, score_tl):
        schema = prinner() | {"stages": []}
        instance, reason = score_tl.create_component(
            ComponentKind.SCHEMA_INSTANCE, schema=schema, degrees=[]
        )
        assert instance is None
        assert "schema" in reason

    @pytest.mark.parametrize(
        "degrees",
        [
            [placed(stage=4)],
            [placed(notehead="")],
            [placed(voice="soprano")],
            [placed(index=-1)],
            [placed(), placed()],  # same notehead twice
            "not a list",
        ],
    )
    def test_create_with_invalid_degrees_fails(self, score_tl, degrees):
        instance, _ = score_tl.create_component(
            ComponentKind.SCHEMA_INSTANCE, schema=prinner(), degrees=degrees
        )
        assert instance is None

    def test_set_degrees(self, score_tl):
        instance, _ = score_tl.create_component(
            ComponentKind.SCHEMA_INSTANCE, schema=prinner(), degrees=[placed()]
        )
        degrees = [placed(), placed("n1", stage=1, value=5)]
        _, success = score_tl.set_component_data(instance.id, "degrees", degrees)
        assert success
        assert instance.degrees == degrees

    def test_schema_must_fit_placed_degrees(self, score_tl):
        instance, _ = score_tl.create_component(
            ComponentKind.SCHEMA_INSTANCE,
            schema=prinner(),
            degrees=[placed(stage=3)],
        )
        shorter = copy.deepcopy(prinner())
        shorter["stages"] = shorter["stages"][:2]
        _, success = score_tl.set_component_data(instance.id, "schema", shorter)
        assert not success

    def test_serialization_round_trip(self, score_tl):
        instance, _ = score_tl.create_component(
            ComponentKind.SCHEMA_INSTANCE, schema=prinner(), degrees=[placed()]
        )
        serialized = score_tl.component_manager.serialize_components()
        data = serialized[instance.id]
        assert data["kind"] == "SCHEMA_INSTANCE"
        assert data["schema"] == prinner()
        assert data["degrees"] == [placed()]

    def test_scaling_and_cropping_leave_instances(self, score_tl):
        # They have no time: where they are follows from their noteheads.
        score_tl.create_component(
            ComponentKind.SCHEMA_INSTANCE, schema=prinner(), degrees=[placed()]
        )
        score_tl.component_manager.scale(2)
        score_tl.component_manager.crop(1)
        assert (
            len(score_tl.get_components_by_attr("KIND", ComponentKind.SCHEMA_INSTANCE))
            == 1
        )
