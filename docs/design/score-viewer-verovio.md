# Score viewer rework: Verovio + WebEngine

**Status:** design — not yet implemented.
**Spike:** `C:\Users\Felipe\dev\verovio` (separate uv project, not a branch). See its `README.md` and `FINDINGS.md` for the verified end‑to‑end demo and the SVG‑Tiny‑1.2 dead‑end writeup.

## What we have today

The dock‑widget score viewer (distinct from the in‑timeline score elements drawn in `tilia/ui/timelines/score/element/`) is:

- **Engraver:** OpenSheetMusicDisplay 1.8.9 — VexFlow under the hood, hence the `vf-stavenote` / `vf-text` classes the parser relies on. "VexFlow" is shorthand for OSMD here.
- **Pipeline:** `tilia/parsers/score/musicxml.py` injects `<fingering>m␟d␟D</fingering>` markers per note, hands the MusicXML to a hidden `QWebEngineView` running OSMD (`tilia/parsers/score/musicxml_to_svg.py` + `svg_maker.html`), receives the SVG back via `QWebChannel` (`SvgWebEngineTracker.set_svg`), persists it as `ScoreTimeline.svg_data`.
- **Viewer:** `tilia/ui/windows/svg_viewer.py` — `QGraphicsScene` + a single shared `QSvgRenderer`; one `QGraphicsSvgItem` background plus one `SvgStaveNote` per `vf-stavenote` for hit‑testing. `_get_beat_x_pos` strips out the `vf-text` markers and builds the `(measure + beat_div/max_div) → x` map kept in `viewer_beat_x`.
- **Coupling:** TLA text annotations (`SvgTlaAnnotation`) are scene‑coordinate overlays. Click→seek goes through the same beat‑x table. The measure tracker is on the *timeline*, not the score, and just needs "what time range is the score viewport showing" — `update_measure_tracker` ↔ `_get_time_from_scene_x`.

The serialized payload per `.tla` is the OSMD SVG (large) plus the beat‑x dict.

## Spike conclusion

`QWebEngineView` + `verovio-toolkit-wasm.js` is the recommended path. Reasons that hold up:

- QtWebEngine is already shipped (YouTube player), so no new runtime dependency.
- The JS toolkit gives us pages, `renderToTimemap`, `getTimeForElement`, `getElementsAtTime`, MEI ids, layout reflow — i.e. everything the hand‑rolled `vf-text` marker hack reproduces, plus things we don't have (timemap‑driven highlight, click‑to‑seek with sub‑note resolution, MIDI playback if we ever want it).
- Verified end‑to‑end on Für Elise: 3 pages, 729 timemap events, click bridge round‑trips MEI ids and ms.
- The SVG‑Tiny‑1.2 `QSvgWidget` path was made to work via `patch_svg.py` but loses interactivity; keep it as documented fallback only.

The spike includes a working reference `qt_webengine_app.py` (~70 LOC PySide6 host) and `web/viewer.html` (~150 LOC in‑page viewer) that already does click‑to‑id, page navigation, zoom, and demo playback highlight.

## Proposed architecture

### Layout

```
tilia/parsers/score/
    musicxml.py                 (no marker injection in the new path)
    svg_maker.html              (REMOVED with VexFlow, see transition)
    musicxml_to_svg.py          (REMOVED with VexFlow)

tilia/ui/windows/score/
    score_view.py               (NEW: ScoreView dock widget, replaces SvgViewer)
    web/
        viewer.html             (vendored from spike, edited for TiLiA)
        verovio-toolkit-wasm.js (~7 MB, LGPL-3, vendored)
        qwebchannel.js          (~16 KB, MIT, vendored)
```

### Python side (`ScoreView`)

A `ViewDockWidget` wrapping a `QWebEngineView`. Loads `web/viewer.html` once at construction (so the WASM compile cost is paid lazily on first open, not per‑score). Exposes the same public surface the rest of TiLiA already calls:

- `load_score(mei_or_musicxml: str)` — `runJavaScript("tiliaLoadScore(...)")`
- `scroll_to_time(time, centered)` — JS scrolls the score viewport; the bridge reports back the visible time range
- `highlight(ids: list[str])` — adds `.playing` class
- `update_annotation(id) / remove_annotation(id) / annotation_*` — same API as today, implemented as DOM overlays in the viewer page (HTML/CSS positioned over the SVG, drag handled in JS, persisted via the bridge)

Bridge (`QWebChannel`):

- JS → Python: `tilia.onElementClicked({id, timeMs, page})`, `tilia.onAnnotationDragged({id, x, y})`, `tilia.onViewportChanged({startMs, endMs})`
- Python → JS: `runJavaScript` for load / seek / highlight / zoom

### What replaces what

| Current | Verovio path |
|---|---|
| `_get_beat_x_pos` extracting `vf-text` markers | `toolkit.renderToTimemap()` once at load; `getTimeForElement(id)` per click |
| `SvgStaveNote` per‑note `QGraphicsSvgItem` for click | JS click handler on `g.note, g.chord, g.rest`; bridge fires id+time |
| `_get_time_from_scene_x` for measure‑tracker | JS `getElementsAtTime` on viewport edges → `onViewportChanged(startMs, endMs)` |
| `SvgTlaAnnotation` (`QGraphicsSimpleTextItem`) | DOM `<div class="tla">` absolutely positioned via `toolkit.getElementBounds` (Verovio API) or computed from the rendered SVG element's `getBoundingClientRect` |
| Custom `paint()` selection tint | CSS `.selected` class toggle |
| Note color (the fix on `fix/494-score-note-color`) | CSS `style="color: …; fill: …"` injected per id (or class) |
| `viewer_beat_x` dict | not needed; timemap supersedes it |

### Persistence

Real decision point.

The cleanest move: **stop storing the engraved SVG. Store the source MEI** (or MusicXML if we want to keep it as‑imported).

- MEI is much smaller than the OSMD SVG, semantically meaningful, and stable under Verovio re‑renders (MEI ids persist).
- Re‑render cost is ~150 ms/page on Für Elise; acceptable on score‑viewer open.
- Eliminates the whole `viewer_beat_x` migration story — just call `renderToTimemap()` after `loadData`.

`ScoreTimeline` becomes:

```python
SERIALIZABLE = ["height", "is_visible", "name", "ordinal", "score_data"]
NOT_EXPORTABLE_ATTRS = ["score_data"]
# score_data = {"format": "mei"|"svg-osmd-legacy", "payload": str}
```

Old `.tla` files have `svg_data` populated; deserialization wraps that as `{"format": "svg-osmd-legacy", "payload": svg_data}`. New files write `{"format": "mei", ...}`.

## Transition plan: both engines available

Two viable shapes for coexistence:

### Shape A — picked by file format (recommended)

The legacy backend is selected automatically if a loaded `.tla` only has `svg_data`. Newly imported scores always use Verovio. No user‑facing setting. The legacy backend ships in read‑only mode: it can display, scroll, click‑to‑seek, and edit annotations on existing files, but new MusicXML imports never go through it. After one or two releases without bug reports, drop the legacy path.

- **Pro:** minimal user surface area; the user never has to choose.
- **Pro:** every new score gets the new engine; bug discovery is fast.
- **Con:** a user who hits a Verovio bug can't "switch back" for a fresh file; their workaround is "wait for a fix."

### Shape B — explicit setting (`score_engine = verovio | osmd`)

Same as A, except the user can force OSMD on new imports during the transition. Adds a settings entry, a re‑import code path, and one extra test matrix axis.

- **Pro:** explicit escape hatch.
- **Con:** doubles the supported "is this bug in OSMD or Verovio" surface; people stay on OSMD by inertia.

**Recommendation: Shape A.** If the spike's Für Elise verification holds across a few real `.tla` files in the library, the OSMD path becomes a backwards‑compat reader, not a parallel feature.

### Shared interface

Both backends sit behind one Python class — call it `ScoreView` — defined by what `ScoreTimelineUI` already calls into: `load_score`, `scroll_to_time`, `update_annotation`, `remove_annotation`, `is_svg_loaded` (rename → `is_score_loaded`), `update_measure_tracker`, the toolbar actions. The legacy `SvgViewer` keeps its current implementation but gets renamed to `LegacyScoreView` and is selected only when `score_data["format"] == "svg-osmd-legacy"`.

Tests: split `tests/ui/timelines/score/test_score_timeline_ui.py` into engine‑agnostic (interface contract) and engine‑specific (rendering specifics, marker parsing for legacy, timemap consumption for Verovio).

## Honest evaluation of dual‑engine

Dual code paths are a tax. The actual tax:

- **Two viewers** sharing one interface: ~250 LOC of legacy `SvgViewer` stays. Maintenance burden is roughly "don't break it" — no new features go in.
- **Two persistence formats:** small and self‑contained behind the `score_data` dispatch.
- **Two test fixtures:** necessary as long as `.tla` files in the wild use `svg_data`. We don't get to drop these on day one.
- **One CI matrix:** the legacy path doesn't need WebEngine for new functionality (just for showing the existing SVG, which it already does today).

The win: the new path simplifies the *viewer‑side* code substantially (the `_get_beat_x_pos` + `_get_time_from_scene_x` + `SvgStaveNote` triangle disappears, replaced by ~five JS callbacks plus `getTimeForElement`). And we stop re‑inventing what Verovio gives us.

If we *don't* support legacy `svg_data` reads, we silently break every `.tla` ever saved with a score timeline. So the legacy reader is non‑negotiable; the only real question is whether to also leave OSMD writes available during transition (Shape B). The recommendation is no.

## Risks

- **LGPL‑3 attribution** for `verovio-toolkit-wasm.js`. We vendor it unmodified, so attribution + a NOTICE pointer to upstream source is enough; verify against TiLiA's license terms before shipping.
- **Bundle size +7 MB** for the WASM toolkit. Acceptable for a desktop installer, worth a one‑line note in the release.
- **Linux font rendering inside QtWebEngine.** The spike was Windows‑only; SMuFL fonts (Bravura, Leland) are bundled in the toolkit, but verify on Linux/macOS before committing to Shape A.
- **Annotation parity.** The drag‑and‑edit feel for TLA annotations must not regress; this is the only piece of the rework that touches user muscle memory. Plan to spend more time here than seems necessary.
- **Startup cost.** 2–4 s WASM warmup on first open. Either lazy (open‑on‑demand, current behavior) or warm at app startup hidden. Lazy is fine; users open the score viewer maybe once per session.

## Suggested order

1. Vendor `verovio-toolkit-wasm.js`, `qwebchannel.js`, and a TiLiA‑edited `viewer.html` under `tilia/ui/windows/score/web/`. Add LGPL‑3 attribution.
2. Build `ScoreView` (the Verovio one) behind a feature flag (env var `TILIA_SCORE_ENGINE=verovio`). Wire it for new imports only; existing `.tla` keep using the current viewer.
3. Reach functional parity: click‑to‑seek, scroll‑to‑time, measure tracker via `onViewportChanged`, note color (CSS), select tint.
4. Port TLA annotations to DOM overlays. This is the riskiest step — bench it against the existing feel.
5. Switch persistence: introduce `score_data = {"format": ..., "payload": ...}`, dispatch on load. Keep writing legacy SVG behind the flag for one release so bisects are easy.
6. Flip the default. Remove the env‑var flag. Legacy `SvgViewer` becomes `LegacyScoreView`, read‑only.
7. After a release without regressions, delete `LegacyScoreView`, `svg_maker.html`, `musicxml_to_svg.py`, the marker injection in `musicxml.py`, and `viewer_beat_x` from `ScoreTimeline.SERIALIZABLE`.

The spike already proves steps 1–3 are feasible; the project work is steps 4–7.

## Open questions for the next session

- Confirm Verovio's licensing terms against TiLiA's distribution model. LGPL‑3 dynamic linking is fine for an unmodified vendored JS bundle; double‑check with the JOSS submission's license decisions.
- Decide whether `score_data["payload"]` for the new path is MEI (Verovio's native, smaller, stable ids) or MusicXML (matches what the user imported). Recommendation in this doc is MEI; verify by round‑tripping a few real scores through `toolkit.getMEI()` and re‑rendering.
- Validate WebEngine font rendering on Linux and macOS before committing to Shape A. The spike was Windows‑only.
- Decide whether the `ScoreView` class lives under `tilia/ui/windows/` (consistent with current `svg_viewer.py`) or gets its own `tilia/ui/windows/score/` package (recommended in this doc, since it owns vendored web assets).
- Score annotation drag/edit UX in DOM overlays — will need a small interactive prototype before committing to the approach.
