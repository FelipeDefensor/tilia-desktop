import json

from tests.mock import Serve
from tilia.file.file_manager import open_tla
from tilia.file.migration import (
    _parse_version,
    is_from_newer_version,
    migrate,
)
from tilia.requests import Get
from tilia.timelines.harmony.timeline import HarmonyTimeline
from tilia.ui import commands


def make_timeline(kind, **extra):
    return {
        "height": 220,
        "is_visible": True,
        "name": "tl",
        "ordinal": 1,
        "components": {},
        "kind": kind,
        **extra,
    }


def make_harmony(**extra):
    return {
        "time": 0,
        "step": 0,
        "accidental": 0,
        "quality": "major",
        "level": 1,
        "kind": "HARMONY",
        **extra,
    }


def make_pre_0_1_1_timeline(kind, display_position, **extra):
    """A timeline dict as written before the 0.1.1 ordinal migration.

    Pre-0.1.1 files have ``display_position``, not ``ordinal``.
    """
    timeline = make_timeline(kind, display_position=display_position, **extra)
    del timeline["ordinal"]
    return timeline


def make_tla(version, timelines=None):
    return {
        "file_path": "",
        "media_path": "",
        "media_metadata": {},
        "timelines": timelines or {},
        "app_name": "TiLiA",
        "version": version,
    }


class TestParseVersion:
    def test_simple(self):
        assert _parse_version("0.6.2") == (0, 6, 2)

    def test_ignores_suffix(self):
        assert _parse_version("0.7.0rc1") == (0, 7, 0)

    def test_empty_sorts_first(self):
        assert _parse_version("") == (0,)
        assert _parse_version("") < _parse_version("0.0.1")

    def test_ordering(self):
        assert _parse_version("0.6.2") < _parse_version("0.7.0")
        assert _parse_version("0.7.0") < _parse_version("0.7.1")
        assert _parse_version("0.7.0") < _parse_version("1.0.0")


class TestIsFromNewerVersion:
    def test_newer(self):
        assert is_from_newer_version(make_tla("0.8.0"), app_version="0.7.0")

    def test_equal(self):
        assert not is_from_newer_version(make_tla("0.7.0"), app_version="0.7.0")

    def test_older(self):
        assert not is_from_newer_version(make_tla("0.6.2"), app_version="0.7.0")

    def test_missing_version(self):
        data = make_tla("0.7.0")
        del data["version"]
        assert not is_from_newer_version(data, app_version="0.7.0")


class TestMigrate:
    def test_display_position_to_ordinal(self):
        data = make_tla(
            "0.1.0",
            {"0": make_pre_0_1_1_timeline("MARKER_TIMELINE", display_position=3)},
        )

        migrated, applied = migrate(data, app_version="0.6.2")

        tl = migrated["timelines"]["0"]
        assert tl["ordinal"] == 4  # display_position + 1
        assert "display_position" not in tl
        assert "0.1.1" in applied

    def test_kind_migration_dormant_below_target_app_version(self):
        # On a pre-0.7 app, the kind must stay in the old format the app reads.
        data = make_tla("0.6.0", {"0": make_timeline("MARKER_TIMELINE")})

        migrated, applied = migrate(data, app_version="0.6.2")

        assert migrated["timelines"]["0"]["kind"] == "MARKER_TIMELINE"
        assert applied == []

    def test_kind_migration_active_at_target_app_version(self):
        data = make_tla("0.6.2", {"0": make_timeline("MARKER_TIMELINE")})

        migrated, applied = migrate(data, app_version="0.7.0")

        assert migrated["timelines"]["0"]["kind"] == "Marker"
        assert applied == ["0.7.0"]
        assert migrated["version"] == "0.7.0"

    def test_chaining_runs_all_applicable_migrations(self):
        data = make_tla(
            "0.1.0",
            {"0": make_pre_0_1_1_timeline("HIERARCHY_TIMELINE", display_position=0)},
        )

        migrated, applied = migrate(data, app_version="0.7.0")

        tl = migrated["timelines"]["0"]
        assert tl["ordinal"] == 1
        assert "display_position" not in tl
        assert tl["kind"] == "Hierarchy"
        assert applied == ["0.1.1", "0.6.0", "0.7.0"]
        assert migrated["version"] == "0.7.0"

    def test_harmony_chord_display_mode_becomes_letter(self):
        data = make_tla(
            "0.5.14",
            {
                "0": make_timeline(
                    "HARMONY_TIMELINE",
                    components={
                        "1": make_harmony(display_mode="chord"),
                        "2": make_harmony(display_mode="roman"),
                        "3": make_harmony(display_mode="custom"),
                        "4": {"kind": "MODE", "time": 0},
                    },
                )
            },
        )

        migrated, applied = migrate(data, app_version="0.6.0")

        components = migrated["timelines"]["0"]["components"]
        assert components["1"]["display_mode"] == "letter"
        assert components["2"]["display_mode"] == "roman"
        assert components["3"]["display_mode"] == "custom"
        assert "display_mode" not in components["4"]
        assert applied == ["0.6.0"]

    def test_harmony_display_mode_untouched_from_0_6_0(self):
        # "chord" is not a valid mode from 0.6.0 on; leave it for validation.
        data = make_tla(
            "0.6.0",
            {
                "0": make_timeline(
                    "HARMONY_TIMELINE",
                    components={"1": make_harmony(display_mode="chord")},
                )
            },
        )

        migrated, applied = migrate(data, app_version="0.6.5")

        assert migrated["timelines"]["0"]["components"]["1"]["display_mode"] == (
            "chord"
        )
        assert applied == []

    def test_current_file_is_noop(self):
        data = make_tla("0.6.2", {"0": make_timeline("MARKER_TIMELINE")})

        migrated, applied = migrate(data, app_version="0.6.2")

        assert applied == []
        assert migrated["timelines"]["0"]["kind"] == "MARKER_TIMELINE"
        assert migrated["version"] == "0.6.2"

    def test_defensive_with_missing_fields(self):
        # Empty timelines and a kind already in new format must not raise.
        data = make_tla("0.1.0")
        migrate(data, app_version="0.7.0")

        data = make_tla("0.1.0", {"0": {"kind": "Marker"}})
        migrated, _ = migrate(data, app_version="0.7.0")
        assert migrated["timelines"]["0"]["kind"] == "Marker"


class TestOpenPre060HarmonyFile:
    def test_chord_display_mode_loads_as_letter(
        self, qtui, tls, tilia_errors, tmp_path
    ):
        harmony_tl = make_timeline(
            "HARMONY_TIMELINE",
            level_count=1,
            level_height=35,
            visible_level_count=2,
            components={"2": make_harmony(time=10, display_mode="chord")},
        )
        del harmony_tl["height"]  # derived from level_height; not serialized
        data = make_tla("0.5.14", {"1": harmony_tl})
        data["media_metadata"] = {"media length": 100}
        path = tmp_path / "old_harmony.tla"
        path.write_text(json.dumps(data), encoding="utf-8")

        commands.execute("file.open", path)

        tilia_errors.assert_no_error()
        (harmony_tl,) = tls.get_timelines_by_type(HarmonyTimeline)
        (harmony,) = harmony_tl.components
        assert harmony.get_data("display_mode") == "letter"


class TestOpenTlaNewerVersionWarning:
    def _write(self, tmp_path, data):
        path = tmp_path / "newer.tla"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_decline_aborts_open(self, tmp_path):
        path = self._write(tmp_path, make_tla("99.0.0"))

        with Serve(Get.FROM_USER_YES_OR_NO, False):
            success, file, old_path = open_tla(path)

        assert success is False
        assert file is None

    def test_accept_proceeds_with_open(self, tmp_path):
        path = self._write(tmp_path, make_tla("99.0.0"))

        with Serve(Get.FROM_USER_YES_OR_NO, True):
            success, file, _ = open_tla(path)

        assert success is True
        assert file is not None
