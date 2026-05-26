# Integration-branch feature catalog

*Internal reference — last updated 2026-05-22.*

This catalogs the features that live **only on the `integration` branch** — i.e. the diff
against **`dev`** (the upstream PR target; local `dev` tracks `upstream/dev`). For each feature
it records what it does, how a user triggers it, where its code and tests are, and whether it
has an open / merged PR. It is a maintenance aid for working on this branch — **not**
user-facing help and not the roadmap.

**Status:** every feature listed here is treated as **pending review** — nothing is assumed
merge-ready. Use this as the review / triage worklist.

**PR column / field** — `up` = upstream (`TimeLineAnnotator/desktop`), `fork` =
(`FelipeDefensor/tilia-desktop`); `—` = no PR (the feature may still be staged on a local
branch, noted per entry). Note a feature can appear in the diff yet already be **merged**
upstream, because cross-fork merges re-write commit SHAs (e.g. window title, `up #398`).

**Keeping it current:** re-derive the feature list with `git log --oneline dev..integration`.
Pure refactor / chore / style / type-hint commits are intentionally excluded; only
user-visible features and the fixes tied to them are listed.

---

## Summary

| Feature | Trigger | Tested? | PR |
|---|---|---|---|
| Range timeline | Add timeline ▸ **Range**; add range = `r` / toolbar | ✓ | up #501 (open) |
| AudioWave timeline rework | automatic (add / open file) | ✓ | up #509 (closed); fork #13 (open) |
| Duplicate timeline | Manage Timelines ▸ **Duplicate** | ✓ | — |
| Pitch-preserving playback rate | player-toolbar rate control | ✓ | — |
| Flexible Ctrl+K seek grammar | **`Ctrl+K`** | ✓ | — |
| Repeat last Ctrl+K seek | **`Ctrl+.`** | ✓ | — |
| Seek to selected element | **`P`** | ✓ | — |
| Snap to downbeat / Snap to measure | element context menu | ✓ | — |
| Set beats-in-measure across selection | Inspector (beat tl) | ✓ | fork #17 (open) |
| Hover guideline across timelines | View ▸ **Show hover guideline** | ✓ | — |
| Hover time / measure in status bar | hover (automatic) | ✓ | — |
| Current measure in player-toolbar label | playback (automatic) | ✓ | — |
| "Length (measures)" inspector row | select hierarchy / range element | ✓ | — |
| Shared-shortcut routing (`S` / `E`) | keypress | ✓ | — |
| Filename / title in window title | file open (automatic) | ✓ | up #398 (merged) |
| Long-running status messages | automatic (background work) | incidental | — |
| Keep main window on top over PDF/video `phd:` | automatic | none | — |
| Resize app on file open `phd:` | automatic | partial | — |

`phd:` = research-specific feature (committed with a `phd:` prefix); may not be intended for upstream.

---

## Playback & seeking

### Pitch-preserving playback rate
- **What:** Changing the playback rate of local audio no longer shifts pitch (time-stretch).
- **Trigger:** the existing rate control in the player toolbar.
- **Code:** `tilia/media/player/` (stretch render helper).
- **Tests:** `tests/player/test_audio_pitch_preserving_rate.py`.
- **Origin:** `386ad8fa`; render-stability fixes `ffe70581`, `82de152b`.
- **PR:** none.

### Flexible Ctrl+K seek grammar
- **What:** `Ctrl+K` opens a seek dialog accepting more than a bare measure number — absolute
  `Ns` / `Nb` / `Nm` (seconds / beats / measures) and relative `±N` / `±Nu`; result clamped to
  `[0, media duration]`.
- **Trigger:** **`Ctrl+K`** (`QShortcut`, `tilia/ui/timelines/collection/collection.py:164`).
- **Code:** `tilia/ui/timelines/collection/collection.py` (`seek_to_measure_action`).
- **Tests:** `tests/ui/timelines/test_seek_to_measure.py`.
- **Origin:** `3d51ae53` (base), `8a22bed1` (grammar); fixes `67a3a130` (uses any beat timeline,
  not a hardcoded "Measures"), `a38c2ad3` (under load).
- **PR:** none.

### Repeat last Ctrl+K seek
- **What:** Replays the most recent successful `Ctrl+K` seek without reopening the dialog.
  Relative seeks (`+1m`, `+5s`, …) are re-resolved from the *current* position, so repeating
  advances cumulatively (e.g. step measure by measure); absolute seeks re-land on the same spot.
  No-op until a seek has succeeded; failed seeks are not stored.
- **Trigger:** **`Ctrl+.`** (`QShortcut`, `tilia/ui/timelines/collection/collection.py`).
- **Code:** `tilia/ui/timelines/collection/collection.py` (`on_repeat_last_seek`, `_perform_seek`,
  `last_seek`).
- **Tests:** `tests/ui/timelines/test_seek_to_measure.py` (`TestRepeatLastSeek`).
- **Origin:** integration branch.
- **PR:** none.

### Seek to selected element
- **What:** Jumps the playhead to the start of the earliest selected element across any timeline.
- **Trigger:** **`P`** (`QShortcut`, `collection.py:172`).
- **Code:** `tilia/ui/timelines/collection/collection.py` (`on_seek_to_selected_element`).
- **Tests:** `tests/ui/timelines/test_seek_to_selected.py`.
- **Origin:** `8a22bed1`; rebound from `Ctrl+J` to `P` in `1958a0ee`.
- **PR:** none.

### Current measure in player-toolbar label
- **What:** The time label gains a measure suffix (e.g. `0:42.31 / 3:51.04 · m. 12`) reflecting
  the bar the playhead is *in*; omitted entirely when no beat timeline exists.
- **Trigger:** automatic during playback / seek.
- **Code:** `tilia/ui/player.py`.
- **Tests:** `tests/ui/test_player_toolbar.py`.
- **Origin:** `2776782e`.
- **PR:** none — staged on `feat/measure-in-toolbar` (+ fix `fix/measure-suffix-in-toolbar`).

### Fix — toggle_play preserves loop position
- **What:** Play/pause inside a loop range no longer jumps the playhead.
- **Code/Tests:** `tilia/media/player/`; `tests/player/test_player.py`.
- **Origin:** `6a4ad635`.
- **PR:** none.

---

## Beat / measure alignment

### Snap to downbeat / Snap to measure
- **What:** Moves a component to the nearest beat ("downbeat") or measure start; for spans
  (hierarchy, range) it moves `start`, for points (marker, PDF) it moves `time`.
- **Trigger:** element **context menu** ▸ "Snap to downbeat" / "Snap to measure".
- **Code:** `tilia/ui/timelines/collection/collection.py` (label/command source).
- **Tests:** `tests/ui/timelines/test_snap_to_downbeat.py`.
- **Origin:** `785d9d17`; fixes `df516476` (redraw hierarchy/range), `a38c2ad3` (under load).
- **PR:** none — staged on `feat/snap-to-measure` (`feat/snap-connected-components` is a separate snap-to-components feature).

### Set beats-in-measure across selection
- **What:** Changing the beats-per-measure value applies to **every** selected measure in one
  pass (previously some reverted).
- **Trigger:** Inspector on a beat timeline with multiple measures selected.
- **Code:** `tilia/timelines/beat/timeline.py`.
- **Tests:** `tests/timelines/beat/test_beat_timeline.py`.
- **Origin:** `74f9465f`.
- **PR:** fork **#17** (open, base `main`) — branch `fix/set-beats-in-measure-bulk`.

---

## Timeline UI & navigation

### Hover guideline across timelines
- **What:** A vertical guideline follows the cursor's X across every timeline; toggleable and
  persisted in settings (`general/show_hover_guideline`, default on).
- **Trigger:** **View ▸ "Show hover guideline"** (checkable; `tilia/ui/menus.py:214`).
- **Code:** `tilia/ui/timelines/view.py`, `tilia/ui/timelines/collection/collection.py:1082`,
  `tilia/ui/menus.py`; setting in `tilia/settings.py:20`.
- **Tests:** `tests/ui/test_hover_guideline.py`.
- **Origin:** `53a03137`; fix `a17e0a7d` (decorative items don't intercept clicks).
- **PR:** none — staged on `feat/hover-guideline` (+ fix `fix/click-through-decorative-items`).

### Hover time / measure in status bar
- **What:** The status bar shows the media time (and measure, if a beat timeline exists) under
  the cursor; clears on leave and on out-of-area hovers.
- **Trigger:** hover over any timeline (automatic).
- **Code:** `tilia/ui/qtui.py` (listens to `Post.TIMELINE_VIEW_HOVER`).
- **Tests:** `tests/ui/test_hover_status_bar.py`.
- **Origin:** `7fc5c850`.
- **PR:** none — staged on `feat/hover-status-bar`.

### Shared-shortcut routing to last-clicked timeline
- **What:** Chords bound to more than one kind (`S` = split, `E` = merge, on both hierarchy and
  range) dispatch to the most-recently-clicked timeline instead of warning "ambiguous".
- **Trigger:** **`S`** / **`E`** keypress.
- **Code:** `tilia/ui/commands.py` (shortcut setup + dispatch); see the convention docstring at
  the top of that file and `tilia/ui/timelines/range/timeline.py:201` for the ambiguity note.
- **Tests:** `tests/ui/timelines/range/test_range_timeline_ui.py`.
- **Origin:** `b98b882a`.
- **PR:** none.

### "Length (measures)" inspector row
- **What:** Hierarchy and range elements get a "Length (measures)" inspector row formatted
  `N m.` or `N m. B b.`; hidden when no beat timeline exists.
- **Trigger:** select a hierarchy or range element.
- **Code:** `tilia/ui/timelines/hierarchy/element.py:51,639`,
  `tilia/ui/timelines/range/element.py:34,481`.
- **Tests:** `tests/ui/windows/test_inspect_length_in_measures.py`.
- **Origin:** `f927b9a8`.
- **PR:** none — staged on `feat/inspect-length-in-measures`.

### Fix — inspector dock resize regression
- **What:** Clicking through components with longer labels no longer grows the inspector dock
  (`right_widget` horizontal size policy stays `Ignored`).
- **Tests:** `tests/ui/windows/test_inspect_resize.py`.
- **Origin:** `7d2ffbe5`; related `b44e9c83` (skip non-inspectable selected elements).
- **PR:** none — staged on `fix/inspector-resize-on-select`.

---

## Timeline kinds & management

### Range timeline
- **What:** A new timeline kind for non-hierarchical labelled time-spans ("ranges") in named
  rows. Ranges have colour, may overlap, may be joined into chains, support copy/paste and
  undo/redo, vertical-arrow row navigation, and CSV import (by-time / by-measure). Exposed in
  the CLI as well.
- **Trigger:** Add timeline ▸ **Range**; add a range with **`r`** or the toolbar (`range-add`,
  `tilia/ui/timelines/range/timeline.py:195`).
- **Code:** `tilia/timelines/range/`, `tilia/ui/timelines/range/`; CSV `tilia/parsers/csv/range.py`.
- **Tests:** `tests/timelines/range/test_range_timeline.py`,
  `tests/ui/timelines/range/test_range_timeline_ui.py`, `tests/parsers/csv/test_range_from_csv.py`.
- **Origin:** `1e0c93b1` (+ ongoing range-PR work).
- **PR:** upstream **#501** (open, base `range-stack-base`) — branch `range-timeline`.
- **Notes:** Largest item; being prepared as a standalone upstream PR. Spec:
  `.ai/range-timeline-requirements.md`; remaining-work checklist: `.todo.md`.

### AudioWave timeline rework
- **What:** Waveform renders asynchronously with a level-of-detail pyramid (no per-sample
  graphics items), a loading spinner, click-to-seek, video/YouTube support with status-bar
  progress, a `frames_per_peak` setting, and a one-time YouTube disclaimer.
- **Trigger:** automatic when an AudioWave timeline is added or a file with one is opened.
- **Code:** `tilia/timelines/audiowave/`, `tilia/ui/timelines/audiowave/`.
- **Tests:** `tests/timelines/audiowave/test_*.py` (timeline, cache, extract, peaks, youtube),
  `tests/ui/timelines/audiowave/test_audiowave_timeline_ui.py`.
- **Origin:** `998dfe0f`; render-crash fixes `ffe70581`, `82de152b`.
- **PR:** upstream **#509** (closed) + fork **#13** (open, base `dev`) — branch `audio-timeline-rework`.

### Duplicate timeline
- **What:** Clones a timeline (all components, fresh IDs) below the original. Slider / score /
  audiowave kinds opt out.
- **Trigger:** **Manage Timelines** window ▸ "Duplicate".
- **Code:** command `tilia/ui/timelines/collection/collection.py:385` (`timeline.duplicate`);
  logic `tilia/timelines/collection/collection.py:176` (`duplicate_timeline`).
- **Tests:** `tests/timelines/test_timeline_duplicate.py`, `tests/ui/windows/test_manage_timelines.py`.
- **Origin:** `643069b9`.
- **PR:** none.

---

## App, window & status

### Filename / title in window title
- **What:** The main window title shows the open file's name / title (e.g. `TiLiA — <name>`),
  useful when several instances are open.
- **Trigger:** automatic on file open / new project.
- **Code:** `tilia/ui/qtui.py`, `tilia/file/file_manager.py`.
- **Tests:** `tests/test_app.py`.
- **Origin:** `ebac4501`.
- **PR:** upstream **#398** (**merged**) — branch `window-title`. Already upstreamed; the
  integration commit is a re-applied copy (different SHA, hence still in the diff).

### Long-running status messages
- **What:** `Post.STATUS_MESSAGE_SET(text, fraction)` / `Post.STATUS_MESSAGE_CLEAR` drive a
  status-bar message with optional progress (fraction in `[0,1]`, or `-1` for indeterminate),
  used by background workers such as waveform extraction.
- **Trigger:** automatic.
- **Code:** `tilia/requests/post.py:68` (`STATUS_MESSAGE_CLEAR`/`STATUS_MESSAGE_SET`); handler in
  `tilia/ui/qtui.py`.
- **Tests:** none dedicated (exercised incidentally in `tests/player/test_audio_pitch_preserving_rate.py`).
- **Origin:** `eeb31f23`.
- **PR:** none.

### Keep main window on top over PDF/video `phd:`
- **What:** The main TiLiA window stays above the PDF/video view window.
- **Trigger:** automatic when opening a PDF or video window.
- **Code:** `tilia/app.py`.
- **Tests:** none.
- **Origin:** `2025d200`; related `d17b7e3b` (defer `ViewWindow.show()` to next event-loop tick).
- **PR:** none.

### Resize app on file open `phd:`
- **What:** The app window resizes when a file is opened.
- **Trigger:** automatic on file open.
- **Code:** `tilia/app.py`.
- **Tests:** partial — `tests/file/test_file_manager.py` / `tests/test_app.py`.
- **Origin:** `556050be`; related `027dfec6` (guard `Get.MAIN_WINDOW` in `load_media`/`on_open`).
- **PR:** none — related fix staged on `fix/main-window-guard`.

---

## Minor UX tweaks & supporting fixes
- Rename & relocate "Move timeline up/down" — `45d98d9d`.
- Rename "Set name" → "Set timeline name" — `deec0844`.
- Skip `QGraphicsItems` with `ignore_right_click=True` on right click — `3338842a`.
- `test_inspect_resize` / inspector-selection fixes — see *inspector dock resize regression* above.
- Internal (not user-visible): post `APP_STATE_UNDO_OR_REDO_DONE` on redo — `483faab6`.
