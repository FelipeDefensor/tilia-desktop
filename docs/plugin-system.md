# TiLiA Plugin System — Implementation Plan

## Context

TiLiA needs a plugin system to support research features and development experiments that aren't ready for production. The system must be modular from the core codebase, allow full data model access (including new timeline types), operate at startup (no runtime reload required), and store enabled plugins in a config file. Plugins will live both bundled in `tilia/plugins/` and in a user folder (`~/.tilia/plugins/`).

This plan is based on the `lcma` branch, which already contains: the new `commands.py` command registry, the `MenuItemKind.COMMAND` refactor, and a rough single-file `lcma.py` plugin hardcoded in `boot.py`. The full plugin system replaces and formalizes that.

---

## Lessons from Established Plugin Systems

### QGIS (Python/Qt — most directly analogous)
- **Adopt:** The `iface`/`api` object pattern — a stable API object passed to each plugin at init time is well-validated at scale.
- **Adopt:** An explicit entry point (`Plugin` class in `__init__.py`) rather than scanning for subclasses. Unambiguous, easy to document.
- **Avoid:** Manual cleanup in `unload()` — QGIS plugins must manually de-register every signal and menu item. Easy to forget, causes leaks.
- **Avoid:** No custom layer type support — QGIS plugins can't add new layer types. Our `register_timeline_type()` is a deliberate improvement over this.

### Obsidian (TypeScript/Electron — best API design)
- **Adopt:** Auto-cleanup via `register_event()` / `add_command()`. Every API call that registers something pushes a cleanup closure onto an internal list. `teardown()` runs all cleanups automatically. Plugin authors almost never need to write teardown code.
- **Adopt:** Per-plugin `load_data()` / `save_data()` — each plugin owns a single JSON blob on disk. Simpler and safer than key-by-key settings.
- **Adopt:** Contribution-model naming — `add_command`, `add_menu`, `register_event` (vs. imperative `register_command`, `listen`). Signals to the author that the framework manages the lifecycle.
- **Avoid:** No version contract on the API — Obsidian updates frequently break plugins. TiLiA should document which API methods are stable.

### Audacity (C++/Nyquist — audio tool with distinct plugin categories)
- **Adopt:** Categorize plugins by capability type. Audacity distinguishes effects, generators, analyzers, and tools. TiLiA plugins should declare their capabilities (commands, timeline types, component types) in class attributes — useful for future tooling and a manager UI.
- **Adopt:** Non-blocking plugin loading. Audacity blocks startup while scanning VST plugins — users hate it. TiLiA's `discover_and_load()` must be fast; plugins with heavy imports should do lazy loading inside `setup()`.
- **Adopt:** Per-plugin error isolation in the loader. Audacity detects crashing plugins at scan time and skips them. TiLiA's manager should wrap each `setup()` call in `try/except`, log the failure, and continue — one bad plugin must not block the rest.
- **Note:** Audacity's Nyquist `;control` declarative parameter system is elegant inspiration for a future plugin settings UI, if one is ever added.

---

## Plugin Data Storage in `.tla` Files

This is the most architecturally consequential decision. Three categories of plugin data need three different storage strategies.

### Category A — Plugin-owned timelines

Plugin-defined timelines live directly in the **main `timelines` dict** under a plugin-prefixed kind string (e.g., `"plugin:lcma.research"`). They are first-class citizens in the file, alongside core timelines. Self-contained, no stale reference risk.

When a file is opened without the owning plugin loaded:
- The unrecognized timeline is **not rendered** (the kind is unknown to the factory).
- Its raw dict is **quarantined** inside `plugin_data._orphaned_timelines[plugin_id][timeline_id]` so it survives a re-save without the plugin.
- A warning is shown to the user.

### Category B — Annotations on existing core components/timelines

A plugin wants to attach extra fields to existing core objects (e.g., LCMA adds `speaker_id` to each Marker). Replicating the `.tla` structure inside a top-level `plugin_data` key creates stale reference problems: a deleted component's ID lingers in `plugin_data` until the plugin explicitly cleans it up, and undo/redo can cause ID divergence.

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

Stale references are **impossible**: plugin data lives and dies with the component. Undo/redo state snapshots include `_plugin_data` automatically. When a file is opened without the owning plugin, `_plugin_data` is preserved as an opaque field and written back on save — no data loss.

### Category C — File-global plugin metadata

Data not tied to any component or timeline (e.g., LCMA experiment ID, participant list). Lives in the top-level `plugin_data` dict:

```json
{
  "timelines": { ... },
  "plugin_data": {
    "lcma": { "experiment_id": "study_001", "participants": ["Alice", "Bob"] },
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

**Verdict:** Adding `plugin_data` is backward-compatible for *reading* but plugin data is silently lost if re-saved by an older version. For a developer-controlled tool this is acceptable.

---

## Implementation Plan

### Phase 1 — Core Plugin Infrastructure

#### 1.1 `tilia/plugins/plugin.py` — Base class

Auto-cleanup is built into the base class (from Obsidian). Plugin authors almost never need to override `teardown()`.

```python
class TiliaPlugin:
    NAME: str = ""
    VERSION: str = "0.1.0"
    DESCRIPTION: str = ""

    def __init__(self):
        self._cleanups: list[Callable] = []

    def _track(self, cleanup_fn: Callable) -> None:
        """Register a cleanup function to be called on teardown."""
        self._cleanups.append(cleanup_fn)

    def setup(self, api: "TiliaPluginAPI") -> None:
        """Called once after the full UI is ready. Override this."""
        pass

    def teardown(self) -> None:
        """Runs all tracked cleanups in reverse. Override only for extra teardown logic."""
        for fn in reversed(self._cleanups):
            try:
                fn()
            except Exception:
                logger.exception(f"Cleanup error in plugin '{self.NAME}'")
```

#### 1.2 `tilia/plugins/api.py` — Stable plugin API

All registration methods auto-track cleanup. Plugin authors call `add_*` / `register_*` in `setup()` and get correct teardown for free.

```python
class TiliaPluginAPI:
    def __init__(self, plugin: TiliaPlugin):
        self._plugin = plugin
        self._id = plugin.NAME

    # --- Events (auto-deregistered on teardown) ---
    def register_event(self, event: Post, callback: Callable) -> None:
        listen(self._plugin, event, callback)
        self._plugin._track(lambda: stop_listening(self._plugin, event))

    def post(self, event: Post, *args, **kwargs) -> None:
        post(event, *args, **kwargs)

    def get(self, request: Get, *args) -> Any:
        return get(request, *args)

    # --- Commands (auto-deregistered on teardown) ---
    def add_command(self, name, callback, text="", shortcut="", icon="") -> None:
        commands.register(name, callback, text, shortcut, icon)
        self._plugin._track(lambda: commands.deregister(name))

    def execute_command(self, name, *args, **kwargs) -> Any:
        return commands.execute(name, *args, **kwargs)

    # --- UI (auto-removed on teardown) ---
    def add_menu(self, menu_class: type[TiliaMenu]) -> None:
        commands.execute("ui.add_menu", menu_class)
        self._plugin._track(lambda: commands.execute("ui.remove_menu", menu_class))

    # --- Data model registration (auto-deregistered on teardown) ---
    def register_timeline_type(self, kind_id: str, timeline_class, ui_class=None) -> None:
        registries.register_timeline_type(kind_id, timeline_class, ui_class)
        self._plugin._track(lambda: registries.deregister_timeline_type(kind_id))

    def register_component_type(self, kind_id: str, component_class, ui_class) -> None:
        registries.register_component_type(kind_id, component_class, ui_class)
        self._plugin._track(lambda: registries.deregister_component_type(kind_id))

    # --- Per-plugin persistent data (Obsidian-style JSON blob) ---
    def load_data(self) -> dict:
        path = dirs.USER_DATA_DIR / "plugins" / self._id / "data.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def save_data(self, data: dict) -> None:
        path = dirs.USER_DATA_DIR / "plugins" / self._id / "data.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    # --- Component/timeline plugin data (namespaced by plugin ID) ---
    def get_component_plugin_data(self, component) -> dict:
        return getattr(component, "_plugin_data", {}).get(self._id, {})

    def set_component_plugin_data(self, component, data: dict) -> None:
        if not hasattr(component, "_plugin_data"):
            component._plugin_data = {}
        component._plugin_data[self._id] = data

    def get_timeline_plugin_data(self, timeline) -> dict:
        return getattr(timeline, "_plugin_data", {}).get(self._id, {})

    def set_timeline_plugin_data(self, timeline, data: dict) -> None:
        if not hasattr(timeline, "_plugin_data"):
            timeline._plugin_data = {}
        timeline._plugin_data[self._id] = data

    # --- File-global plugin data ---
    def get_file_plugin_data(self) -> dict:
        return get(Get.FILE_PLUGIN_DATA, self._id)

    def set_file_plugin_data(self, data: dict) -> None:
        post(Post.FILE_PLUGIN_DATA_SET, self._id, data)
```

#### 1.3 `tilia/plugins/registries.py` — Type registries

```python
_timeline_registry: dict[str, type[Timeline]] = {}
_timeline_ui_registry: dict[str, type] = {}
_component_registry: dict[str, type[TimelineComponent]] = {}
_component_ui_registry: dict[str, type] = {}

def register_timeline_type(kind_id: str, cls, ui_cls=None): ...
def deregister_timeline_type(kind_id: str): ...
def get_timeline_class(kind_id: str) -> type[Timeline] | None: ...
def register_component_type(kind_id: str, cls, ui_cls): ...
def deregister_component_type(kind_id: str): ...
def get_component_class(kind_id: str) -> type[TimelineComponent] | None: ...
def get_component_ui_class(kind_id: str) -> type | None: ...
```

Kind IDs for plugins use the `"plugin:"` prefix: `"plugin:lcma.research_timeline"`. This prevents collisions with core `TimelineKind` enum values.

#### 1.4 `tilia/plugins/manager.py` — Plugin manager

The manager uses an explicit `Plugin` class entry point (from QGIS), wraps each load in `try/except` (from Audacity), and must complete quickly (Audacity lesson on non-blocking startup).

```python
class PluginManager:
    def discover_and_load(self) -> None:
        builtin_pkgs = self._scan_builtin_dir()
        user_pkgs = self._scan_user_dir()
        config = self._read_config()
        disabled = set(config.get("disabled", []))

        for pkg in builtin_pkgs + user_pkgs:
            if pkg.name not in disabled:
                self._load_plugin(pkg)

    def _load_plugin(self, pkg_path: Path) -> bool:
        try:
            mod = importlib.import_module(pkg_path.name)
            plugin_cls = getattr(mod, "Plugin", None)
            if plugin_cls is None:
                logger.warning(f"Plugin '{pkg_path.name}' has no 'Plugin' class, skipping.")
                return False
            plugin = plugin_cls()
            api = TiliaPluginAPI(plugin)
            plugin.setup(api)
            self._plugins[plugin.NAME] = plugin
            logger.info(f"Loaded plugin '{plugin.NAME}' v{plugin.VERSION}")
            return True
        except Exception:
            logger.exception(f"Failed to load plugin '{pkg_path.name}', skipping.")
            return False

    def unload_all(self) -> None:
        for plugin in reversed(list(self._plugins.values())):
            plugin.teardown()
```

Config file (`data_dir/plugins.json`):
```json
{
  "disabled": [],
  "external_paths": ["/path/to/my/plugin"]
}
```

Built-in plugins (in `tilia/plugins/`) are enabled by default unless listed in `"disabled"`.

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

Update `get_timeline_class_from_kind()` to fall back to the plugin registry for `"plugin:"` prefixed kinds:

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

**Deserialization** — strip `_plugin_data` before constructor, re-attach after:
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

`validate_tla_data()` does not require `plugin_data` (optional field).

#### 2.6 Graceful handling of unknown timeline kinds

In the timeline deserialization loop, wrap creation in `try/except` and quarantine unknown kinds:

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

Convert `tilia/plugins/lcma.py` → `tilia/plugins/lcma/__init__.py`. Explicit `Plugin` entry point (QGIS pattern). Uses `add_command` and auto-cleanup (Obsidian pattern).

```python
# tilia/plugins/lcma/__init__.py
from tilia.plugins.plugin import TiliaPlugin
from tilia.plugins.api import TiliaPluginAPI
from tilia.ui.menus import TiliaMenu, MenuItemKind


class LCMAPlugin(TiliaPlugin):
    NAME = "lcma"
    VERSION = "0.1.0"
    DESCRIPTION = "LCMA Research Tools"

    def setup(self, api: TiliaPluginAPI) -> None:
        self._api = api
        api.add_command(                          # auto-deregistered on teardown
            "lcma.save_and_export_to_json",
            self.save_and_export_to_json,
            text="Save and export",
            shortcut="Ctrl+Shift+J",
        )
        api.add_menu(LCMAMenu)                    # auto-removed on teardown

    def save_and_export_to_json(self):
        from tilia.requests import Get
        self._api.execute_command("file.save")
        file_path = self._api.get(Get.FILE_PATH)
        self._api.execute_command("file.export.json", file_path.replace(".tla", ".json"))


class LCMAMenu(TiliaMenu):
    menu_title = "LCMA"
    items = [(MenuItemKind.COMMAND, "lcma.save_and_export_to_json")]


Plugin = LCMAPlugin  # explicit entry point for the plugin manager
```

---

## Critical Files

| File | Action |
|---|---|
| `tilia/plugins/plugin.py` | **Create** — `TiliaPlugin` base class with auto-cleanup |
| `tilia/plugins/api.py` | **Create** — `TiliaPluginAPI` with contribution-model methods |
| `tilia/plugins/manager.py` | **Create** — `PluginManager` with error isolation |
| `tilia/plugins/registries.py` | **Create** — type registries with deregister support |
| `tilia/plugins/lcma/__init__.py` | **Create** — migrated LCMA plugin (delete `lcma.py`) |
| `tilia/plugins/__init__.py` | Already exists (empty) |
| `tilia/boot.py` | **Modify** — replace hardcoded `LCMAPlugin()` with `PluginManager` |
| `tilia/dirs.py` | **Modify** — add `USER_PLUGINS_DIR`, `PLUGINS_CONFIG_PATH` |
| `tilia/file/tilia_file.py` | **Modify** — add `plugin_data` field |
| `tilia/timelines/serialize.py` | **Modify** — embed `_plugin_data`; handle string kinds |
| `tilia/timelines/timeline_kinds.py` | **Modify** — plugin registry fallback |
| `tilia/timelines/component_kinds.py` | **Modify** — plugin registry fallback |
| `tilia/ui/timelines/element_kinds.py` | **Modify** — plugin registry fallback |

---

## Verification

1. **App starts cleanly**: `python -m tilia` with no errors; LCMA menu appears in menubar.
2. **Command executes**: `Ctrl+Shift+J` triggers save + JSON export.
3. **Auto-cleanup works**: Confirm no leftover commands or listeners after `teardown()`.
4. **Plugin discovery**: Add a minimal second plugin package to `tilia/plugins/`, restart — it loads.
5. **User plugin folder**: Place a plugin in `~/.tilia/plugins/`, restart — it loads.
6. **Per-plugin data**: Call `api.save_data({"key": "val"})`, restart, call `api.load_data()` — data persists.
7. **Component plugin data round-trip**: Add `_plugin_data` to a component in a `.tla` file, open, save — verify preserved in output.
8. **Unknown timeline graceful skip**: Set a timeline kind to `"plugin:unknown.x"` in a `.tla` file — warning shown, core timelines load normally, kind is quarantined.
9. **Error isolation**: Introduce a crash in a plugin's `setup()` — other plugins load normally.
10. **No plugin config**: Delete `plugins.json`, restart — app starts with built-in plugins, no crash.
