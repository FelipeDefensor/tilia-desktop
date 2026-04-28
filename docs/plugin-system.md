# TiLiA Plugin System — Implementation Plan

## Context

TiLiA needs a plugin system to support research features and development experiments that aren't ready for production. The system must be modular from the core codebase, allow full data model access (including new timeline types), operate at startup (no runtime reload required), and store enabled plugins in a config file. Plugins will live both bundled in `tilia/plugins/` and in a user folder (`~/.tilia/plugins/`).

This plan is based on the `lcma` branch, which already contains: the new `commands.py` command registry, the `MenuItemKind.COMMAND` refactor, and a rough single-file `lcma.py` plugin hardcoded in `boot.py`. The full plugin system replaces and formalizes that.

---

## Plugin Data Storage in `.tla` Files

This is the most architecturally consequential decision. Three categories of plugin data need three different storage strategies.

### Category A — Plugin-owned timelines

Plugin-defined timelines (entire new timeline types) live directly in the **main `timelines` dict** under a plugin-prefixed kind string (e.g., `"PLUGIN_LCMA_RESEARCH"`). They are first-class citizens in the file, alongside core timelines. Self-contained, no stale reference risk.

When a file is opened without the owning plugin loaded:
- The unrecognized timeline is **not rendered** (the kind is unknown to the factory).
- Its raw dict is **quarantined** inside `plugin_data._orphaned_timelines[plugin_id][timeline_id]` so it survives a re-save by an installation without the plugin.
- A warning is shown to the user.

### Category B — Annotations on existing core components/timelines

A plugin wants to attach extra fields to existing core objects (e.g., LCMA adds `speaker_id` to each Marker, a research plugin adds `confidence` to Hierarchy components). Replicating the `.tla` structure inside a top-level `plugin_data` key creates stale reference problems and synchronization burden:

- Component is deleted → `plugin_data.lcma.components["42"]` is orphaned; plugin must subscribe to every deletion event to clean it.
- State is restored via undo → IDs may diverge from plugin_data.
- Cross-referencing requires careful bookkeeping.

**Better approach: embed plugin data directly inside the component/timeline dict under `_plugin_data`.**

```json
"components": {
  "42": {
    "kind": "MARKER",
    "time": 12.5,
    "label": "intro",
    "hash": "...",
    "_plugin_data": {
      "lcma": { "speaker": "Alice", "certainty": 0.9 }
    }
  }
}
```

Stale references are **impossible** with this approach: plugin data lives and dies with the component. When the component is deleted, its `_plugin_data` is gone. When undone/redone via state snapshot, the `_plugin_data` is restored alongside the component.

When a file is opened without the owning plugin, `_plugin_data` is preserved as an opaque field on the component and written back on save — no data loss even without the plugin.

### Category C — File-global plugin metadata

Data not tied to any component or timeline (e.g., LCMA experiment ID, participant list, recording conditions). Lives in the top-level `plugin_data` dict:

```json
{
  "timelines": { ... },
  "plugin_data": {
    "lcma": {
      "experiment_id": "study_001",
      "participants": ["Alice", "Bob"]
    },
    "_orphaned_timelines": { ... }
  }
}
```

### Backward compatibility summary

| Scenario | Outcome |
|---|---|
| New TiLiA opens old file (no `plugin_data`) | `plugin_data` defaults to `{}` — fine |
| Old TiLiA opens new file with `plugin_data` key | Key is ignored on load (JSON doesn't fail) |
| Old TiLiA re-saves a file with `plugin_data` | **Lost** — `TiliaFile` dataclass has no such field |
| Old TiLiA re-saves a file with `_plugin_data` in components | **Lost** — serializer only writes `SERIALIZABLE` attrs |
| New TiLiA re-saves with plugin not loaded | Plugin data preserved via pass-through |

**Verdict:** Adding `plugin_data` is backward-compatible for *reading* but plugin data is silently lost if re-saved by an older version. For a developer-controlled tool, this is acceptable. A version check warning can be added later if needed.

---

## Implementation Plan

### Phase 1 — Core Plugin Infrastructure

#### 1.1 `tilia/plugins/plugin.py` — Base class

```python
class TiliaPlugin:
    NAME: str = ""
    VERSION: str = "0.1.0"
    DESCRIPTION: str = ""

    def setup(self, api: "TiliaPluginAPI") -> None:
        """Called once after the full UI is ready."""
        pass

    def teardown(self) -> None:
        """Called at app exit. Override to do cleanup."""
        pass
```

#### 1.2 `tilia/plugins/api.py` — Stable plugin API

Wraps internal systems behind a stable interface so plugins are shielded from internal refactors.

```python
class TiliaPluginAPI:
    def __init__(self, plugin_id: str): ...

    # Events
    def listen(self, event: Post, callback: Callable) -> None
    def post(self, event: Post, *args, **kwargs) -> None
    def get(self, request: Get, *args) -> Any

    # Commands
    def register_command(self, name, callback, text="", shortcut="", icon="") -> None
    def execute_command(self, name, *args, **kwargs) -> Any

    # UI
    def add_menu(self, menu_class: type[TiliaMenu]) -> None

    # Data model registration
    def register_timeline_type(self, kind_id: str, timeline_class, ui_class=None) -> None
    def register_component_type(self, kind_id: str, component_class, ui_class) -> None

    # Component/timeline plugin data access
    def get_component_plugin_data(self, component: TimelineComponent) -> dict
    def set_component_plugin_data(self, component: TimelineComponent, data: dict) -> None
    def get_timeline_plugin_data(self, timeline: Timeline) -> dict
    def set_timeline_plugin_data(self, timeline: Timeline, data: dict) -> None

    # File-global plugin data
    def get_file_plugin_data(self) -> dict
    def set_file_plugin_data(self, data: dict) -> None

    # Plugin settings (per-plugin, persisted in app settings)
    def get_setting(self, key: str, default=None) -> Any
    def set_setting(self, key: str, value: Any) -> None
```

Plugin data accessors read/write from `component._plugin_data[plugin_id]`. File-global data goes through `get(Get.FILE_PLUGIN_DATA, plugin_id)` / `post(Post.FILE_PLUGIN_DATA_SET, ...)`.

#### 1.3 `tilia/plugins/registries.py` — Type registries

```python
_timeline_registry: dict[str, type[Timeline]] = {}
_timeline_ui_registry: dict[str, type] = {}
_component_registry: dict[str, type[TimelineComponent]] = {}
_component_ui_registry: dict[str, type] = {}

def register_timeline_type(kind_id: str, cls, ui_cls=None): ...
def get_timeline_class(kind_id: str) -> type[Timeline] | None: ...
def register_component_type(kind_id: str, cls, ui_cls): ...
def get_component_class(kind_id: str) -> type[TimelineComponent] | None: ...
def get_component_ui_class(kind_id: str) -> type | None: ...
```

Kind IDs for plugins are strings with a `"plugin:"` prefix: `"plugin:lcma.research_timeline"`. This prefix prevents collisions with core `TimelineKind` enum values.

#### 1.4 `tilia/plugins/manager.py` — Plugin manager

```python
class PluginManager:
    def discover_and_load(self) -> None:
        # 1. Scan tilia/plugins/ for built-in plugin packages
        # 2. Read config from data_dir/plugins.json
        # 3. Scan user plugin folder listed in config
        # 4. For each enabled plugin: import, instantiate TiliaPlugin subclass, call setup(api)

    def unload_all(self) -> None:
        for plugin in self._plugins.values():
            plugin.teardown()
```

Config file (`data_dir/plugins.json`):
```json
{
  "enabled": ["lcma"],
  "external_paths": ["/path/to/my/plugin"]
}
```

Built-in plugins (in `tilia/plugins/`) are enabled by default. User can opt out by adding `"disabled": ["built_in_name"]`.

#### 1.5 `tilia/dirs.py` — Add user plugin path

```python
USER_PLUGINS_DIR = Path(platformdirs.user_data_dir(APP_NAME, roaming=True)) / "plugins"
PLUGINS_CONFIG_PATH = Path(platformdirs.user_data_dir(APP_NAME, roaming=True)) / "plugins.json"
```

#### 1.6 `tilia/boot.py` — Wire in PluginManager

Replace the hardcoded `LCMAPlugin()` with:
```python
from tilia.plugins.manager import PluginManager
plugin_manager = PluginManager()
plugin_manager.discover_and_load()
```

Placed after `app.setup_file()` / `app.on_open()` (same position as current `LCMAPlugin()`), before `ui.launch()`.

---

### Phase 2 — Data Model Extension Hooks

#### 2.1 `tilia/timelines/timeline_kinds.py`

Update `get_timeline_class_from_kind()` to fall back to the plugin registry when the kind string starts with `"plugin:"`:

```python
def get_timeline_class_from_kind(kind: TimelineKind | str) -> type[Timeline]:
    if isinstance(kind, str) and kind.startswith("plugin:"):
        cls = registries.get_timeline_class(kind)
        if cls is None:
            raise KeyError(f"No plugin timeline registered for kind '{kind}'")
        return cls
    # existing enum-based lookup via Timeline.subclasses()
    ...
```

#### 2.2 `tilia/timelines/component_kinds.py`

Extend `get_component_class_by_kind()` to check the plugin registry for string kinds:

```python
def get_component_class_by_kind(kind: ComponentKind | str):
    if isinstance(kind, str) and kind.startswith("plugin:"):
        return registries.get_component_class(kind)
    # existing enum lookup
    ...
```

#### 2.3 `tilia/ui/timelines/element_kinds.py`

Same pattern for `get_element_class_by_kind()`.

#### 2.4 `tilia/timelines/serialize.py` — Embed plugin data

**Serialization** — preserve `_plugin_data` if present:
```python
def serialize_component(component):
    serialized = {attr: getattr(component, attr) for attr in component.SERIALIZABLE}
    serialized["kind"] = component.KIND if isinstance(component.KIND, str) else component.KIND.name
    serialized["hash"] = component.hash
    if pd := getattr(component, "_plugin_data", None):
        serialized["_plugin_data"] = pd
    return serialized
```

**Deserialization** — strip `_plugin_data` before passing to constructor, re-attach after:
```python
def _deserialize_component(timeline, id, serialized_component):
    plugin_data = serialized_component.pop("_plugin_data", {})
    kind_str = serialized_component["kind"]

    if kind_str.startswith("plugin:"):
        component_kind = kind_str
        component_class = get_component_class_by_kind(kind_str)
        if component_class is None:
            return None, f"Plugin component type '{kind_str}' not registered"
    else:
        component_kind = ComponentKind[kind_str]
        component_class = get_component_class_by_kind(component_kind)

    constructor_kwargs = _get_component_constructor_kwargs(serialized_component, component_class)
    component, fail_reason = timeline.create_component(component_kind, **constructor_kwargs, id=id)
    if component:
        component._plugin_data = plugin_data
    return component, fail_reason
```

#### 2.5 `tilia/file/tilia_file.py` — Add `plugin_data` field

```python
@dataclass
class TiliaFile:
    ...existing fields...
    plugin_data: dict = field(default_factory=dict)
```

`validate_tla_data()` does not require `plugin_data` (it's optional).

#### 2.6 Graceful handling of unknown timeline kinds

In the timeline deserialization loop (wherever `timelines` are loaded from the file), wrap the timeline creation in a try/except on `KeyError` from `get_timeline_class_from_kind`. On failure, quarantine the raw timeline dict:

```python
try:
    tl_class = get_timeline_class_from_kind(kind)
    # ... create timeline ...
except KeyError:
    logger.warning(f"Unknown timeline kind '{kind}', quarantining.")
    file.plugin_data.setdefault("_orphaned_timelines", {})[tl_id] = tl_data
```

---

### Phase 3 — Migrate LCMA Plugin

Convert `tilia/plugins/lcma.py` to a proper package `tilia/plugins/lcma/__init__.py` using the new infrastructure:

```python
from tilia.plugins.plugin import TiliaPlugin
from tilia.plugins.api import TiliaPluginAPI
from tilia.ui.menus import TiliaMenu, MenuItemKind

class LCMAPlugin(TiliaPlugin):
    NAME = "lcma"
    VERSION = "0.1.0"
    DESCRIPTION = "LCMA Research Tools"

    def setup(self, api: TiliaPluginAPI) -> None:
        api.register_command(
            "lcma.save_and_export_to_json",
            self.save_and_export_to_json,
            text="Save and export",
            shortcut="Ctrl+Shift+J",
        )
        api.add_menu(LCMAMenu)
        self._api = api

    def save_and_export_to_json(self):
        self._api.execute_command("file.save")
        from tilia.requests import Get
        file_path = self._api.get(Get.FILE_PATH)
        self._api.execute_command("file.export.json", file_path.replace(".tla", ".json"))
```

---

## Critical Files

| File | Action |
|---|---|
| `tilia/plugins/plugin.py` | **Create** — `TiliaPlugin` base class |
| `tilia/plugins/api.py` | **Create** — `TiliaPluginAPI` |
| `tilia/plugins/manager.py` | **Create** — `PluginManager` |
| `tilia/plugins/registries.py` | **Create** — type registries |
| `tilia/plugins/lcma/__init__.py` | **Create** — migrated LCMA plugin (delete `lcma.py`) |
| `tilia/plugins/__init__.py` | Already exists (empty) |
| `tilia/boot.py` | **Modify** — replace hardcoded `LCMAPlugin()` with `PluginManager` |
| `tilia/dirs.py` | **Modify** — add `USER_PLUGINS_DIR`, `PLUGINS_CONFIG_PATH` |
| `tilia/file/tilia_file.py` | **Modify** — add `plugin_data` field |
| `tilia/timelines/serialize.py` | **Modify** — embed `_plugin_data` in components; handle string kinds |
| `tilia/timelines/timeline_kinds.py` | **Modify** — plugin registry fallback in `get_timeline_class_from_kind` |
| `tilia/timelines/component_kinds.py` | **Modify** — plugin registry fallback in `get_component_class_by_kind` |
| `tilia/ui/timelines/element_kinds.py` | **Modify** — plugin registry fallback in `get_element_class_by_kind` |

---

## Verification

1. **App starts cleanly**: `python -m tilia` runs with no errors; LCMA menu appears in menubar.
2. **Command executes**: `Ctrl+Shift+J` triggers save + JSON export.
3. **Plugin discovery**: Add a minimal second plugin package to `tilia/plugins/`, restart — it loads.
4. **User plugin folder**: Place a plugin in `~/.tilia/plugins/`, add it to `plugins.json`, restart — it loads.
5. **Plugin data round-trip**: Manually add `_plugin_data` to a component in a `.tla` file, open in TiLiA, save — verify `_plugin_data` is preserved in the output.
6. **Unknown timeline graceful skip**: Set a timeline's `kind` to `"PLUGIN_UNKNOWN_X"` in a `.tla` file, open — verify warning is shown and core timelines load normally.
7. **No plugin config**: Delete `plugins.json`, restart — app starts with built-in plugins only, no crash.
