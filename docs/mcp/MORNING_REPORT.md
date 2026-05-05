# MCP overnight session — morning report

## tl;dr

`tilia --mcp-server` now exposes a streamable-HTTP MCP server with **97
tools**, **6 resources**, and a screenshot capability that lets a remote
client (Claude Code, an MCP-aware agent, or a plain Python script) drive
the running app and read pixels back. With that loop in place I could:

1. **Find a real bug** by exploration alone: TiLiA's main thread hangs
   when `set_duration` is called with a positive value while a
   non-slider timeline exists at duration = 0. Reproducer in
   `scripts/mcp_repro_hang.py`.
2. **Draw the Anthropic asterisk** entirely through MCP calls — every
   row is a hierarchy timeline, every cell a `create_hierarchy` call.
   Screenshot at `docs/mcp/logo_window.png` (also `logo_timelines.png`
   for the cropped timeline-area view).

## Demo for colleagues

```bash
.venv/bin/pip install --group server      # one-time
tilia --mcp-server                         # term 1
.venv/bin/python scripts/mcp_demo.py       # term 2 — basic walkthrough
.venv/bin/python scripts/mcp_logo.py       # term 2 — draws the asterisk
.venv/bin/python scripts/mcp_bughunt.py    # term 2 — edge-case probes
.venv/bin/python scripts/mcp_repro_hang.py # term 2 — minimal hang repro
```

`scripts/mcp_call.py` is a one-shot client for ad-hoc tool/resource calls:

```bash
python scripts/mcp_call.py tool list_timelines '{}'
python scripts/mcp_call.py tool screenshot '{"target": "timelines"}'
python scripts/mcp_call.py resource tilia://state
```

## What was built (server)

Everything new is under `tilia/server/` so the rest of the codebase is
untouched apart from the `--mcp-server` flag in `boot.py` and a new
`server` dependency group in `pyproject.toml`.

```
tilia/server/
  __init__.py        # public start() entry
  bridge.py          # Qt-main-thread invoker + DISPLAY_ERROR capture
  runner.py          # boots the asyncio loop in a daemon thread
  mcp_server.py      # FastMCP instance + curated tools and resources
  extras.py          # granular tools (introspection, mutations, screenshot, window)
  registry.py        # auto-exposes every tilia.ui.commands entry as a tool
```

### Curated tools (27)

`list_commands`, `execute_command`, `open_file`, `save_file`,
`add_timeline`, `add_marker`, `set_duration`, `screenshot`,
`flush_paint`, `resize_window`, `get_window_geometry`, `zoom_in`,
`zoom_out`, `fit_to_duration`, `list_timelines`,
`get_timeline_id_by_name`, `get_components`, `create_timeline`,
`delete_timeline`, `clear_all_timelines`, `create_hierarchy`,
`create_marker`, `set_component_data`, `delete_component`,
`set_timeline_data`, `query`, `list_query_keys`, `recent_errors`,
`clear_recent_errors`.

### Auto-exposed registry (70)

Every entry in `tilia.ui.commands._name_to_callback` becomes its own
MCP tool named `cmd__<sanitized_name>` (e.g. `cmd__file__open`,
`cmd__timeline__hierarchy__split`). The description includes the
inspected callback signature and any pre-bound `functools.partial`
args, and the tool accepts generic `args`/`kwargs` payloads.

### Resources (6)

- `tilia://state` — full app state (timelines + media metadata)
- `tilia://media/duration`, `tilia://media/current_time`, `tilia://media/path`
- `tilia://commands` — registered command names
- `tilia://errors` — recently captured error dialogs (see below)

### Modal dialog capture

TiLiA's default `Post.DISPLAY_ERROR` handler calls
`QMessageBox.exec()`, which freezes the Qt main thread until the user
clicks OK. That makes any automation flow hitting a validator deadlock.
On `start()`, the server replaces that listener with one that pushes
the error into a `deque` (`bridge.recent_errors`) and logs a warning.
Read it back via the `recent_errors` tool or the `tilia://errors`
resource. The tradeoff: while the server is running, the human user
won't see error dialogs either — they have to read the resource.

### Screenshot pipeline

`screenshot(target=window|timelines|timeline, timeline_id=...)` flushes
posted Qt events (`processEvents` → `sendPostedEvents` →
`processEvents`) before calling `widget.grab()`. Returns both a temp
PNG path and inline `ImageContent` so MCP clients render it natively.

## The bug

**Steps to reproduce** (`scripts/mcp_repro_hang.py`):

```text
1. Start TiLiA with --mcp-server (slider timeline auto-created, duration=0)
2. clear_all_timelines       (slider re-created, duration still 0)
3. create_timeline kind=marker
4. set_duration seconds=60   ← Qt main thread hangs forever
```

After step 4 the streamable HTTP request never returns; the GUI stops
responding to clicks too. SIGTERM works, only SIGKILL after that.

The reverse direction (set_duration to 0 while a marker timeline
exists at duration=60) does **not** hang. Going from 0 to non-zero is
the trigger; an empty marker timeline is sufficient (no components
needed). I did not dig into the cause — the spec was to find a bug via
MCP alone, so I stopped at a reliable repro.

If I had to guess: a redraw triggered by
`Post.PLAYER_DURATION_AVAILABLE` recurses or busy-loops because some
geometry calculation that previously divided by 0 is now valid and a
re-entrant signal didn't break the loop. But that's a guess — the next
step is `py-spy dump --pid <pid>` while it's hung.

## Other findings (probes that flagged behaviour worth a look)

From `scripts/mcp_bughunt.py` against the running server:

- **Invalid colors are accepted silently when creating a hierarchy via
  the backend `create_component` path.** A
  `Hierarchy(color="not-a-color")` succeeds — `validate_color` only
  fires on `set_data`, not on `__init__`. Recommendation: validate at
  construction too, or document that the create path skips validators.

- **`set_duration` accepts negative values and stores them.**
  `media_metadata["media length"]` ends up as `-10.0`. Subsequent
  `get_app_state()` round-trips the negative value. Not visibly
  catastrophic but very suspicious; the `MEDIA_METADATA_SET_DATA_FAILED`
  error message in `tilia/errors.py` already says "Media length must
  be a positive number", so the validation exists somewhere but isn't
  reached on this path.

- **`set_duration` accepts `1e9` seconds without complaint.** Probably
  fine, but a guardrail would be cheap.

- **Negative-time error message is malformed.** Trying to add a marker
  at `t=-1` returns `"Time can't be negative. Got '59:59.0'"` —
  `format_media_time` interprets -1 as MM:SS wraparound. Cosmetic but
  user-facing.

- **Embedded NUL bytes round-trip in labels.** `"NULL\x00END"` survives
  state serialisation. Probably harmless given JSON allows it, but
  worth knowing if any downstream importer/exporter assumes
  C-string semantics.

- **Negative timeline height is rejected (good).** `set_timeline_data
  height=-50` fails; height stays at 30.

- **Huge timeline height is accepted unchecked (`100000`).** Renders
  off-screen; UI doesn't clamp.

## The logo

Pattern is an asymmetric 21×21 pixel grid sampled from a hand-built
8-pointed asterisk. Rendering: 21 hierarchy timelines stacked, each
24px tall, painted across a 120s timespan. Each row coalesces runs of
identical pixels into single hierarchy components (so the horizontal
line is one component, the vertical column is many — one per row).

Lit cells use `#cc785c` (Anthropic peach). Dim cells use `#1a1a1a` to
blend with the dark theme. The little visual seams between adjacent
hierarchies aren't gaps in the data — TiLiA renders each hierarchy
with a small inset, which is actually charming for pixel art.

The drawing also revealed a quality-of-life win for the bug above:
`mcp_logo.py` calls `set_duration` **before** creating any non-slider
timelines, so it sidesteps the hang. Without that ordering hint, the
script would freeze on the first `set_duration` call.

## Files added/changed

```
A docs/mcp/MORNING_REPORT.md
A docs/mcp/logo_timelines.png
A docs/mcp/logo_window.png
A scripts/mcp_bughunt.py
A scripts/mcp_call.py
A scripts/mcp_demo.py        (already existed, lightly tweaked for new content blocks)
A scripts/mcp_logo.py
A scripts/mcp_repro_hang.py
A tilia/server/__init__.py
A tilia/server/bridge.py
A tilia/server/extras.py
A tilia/server/mcp_server.py
A tilia/server/registry.py
A tilia/server/runner.py
M pyproject.toml             (+server dependency group)
M tilia/boot.py              (+--mcp-server flag)
```

No source files outside `tilia/server/` were changed beyond those two.
