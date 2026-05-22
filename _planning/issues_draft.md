# TiLiA — feature issue draft

Draft of issues to open from the LCMA meeting notes plus the team backlog (ClickUp).
Review before opening any of these on `TimeLineAnnotator/desktop` or
`TimeLineAnnotator/website`.

## Sources

| Source | Items | Notes |
|---|---:|---|
| **LCMA meeting** (2026-05) | ~30 | Features discussed in lab meeting; marked **★** below |
| **ClickUp — Desktop** | 73 | Full team backlog; mix of features, refactors, UX polish |
| **ClickUp — Web Frontend** | 56 | |
| **ClickUp — Web Backend** | 5 | |
| **GitHub Project** ([TiLiA Roadmap](https://github.com/orgs/TimeLineAnnotator/projects/3)) | 90 | Bugs and a few features for 0.6 |

- Project conventions reused below: `Status` (`Todo` / `In Progress` / `Done`) and
  `Immediacy` (1–6, lower = more urgent).
- `★` = item proposed at the LCMA meeting (per user's request: flag in the drawio
  and the draft, but **not necessarily in the GitHub project**).
- `[CU:<id>]` = ClickUp task ID — for cross-reference, not for an issue body.

## Reconciliation overview

Decisions baked into the draft below:

### ClickUp items that **merge** with LCMA features (one issue, not two)

| LCMA item | ClickUp duplicate(s) |
|---|---|
| ★ 4.3 Link / Reuse component (`#341`) | `Link timeline components by repetition relations` [CU:86a72qxu7] |
| ★ 5.2 Different fill patterns | `Let the user select a brush pattern for hierarchies` [CU:86a72qxf7] |
| ★ 7.1 Snap to metric grid (`#342`) | `Snap to beats` [CU:86a72qxha] |
| ★ 7.4 Automatic beat detection | `Add automatic beat detection` [CU:86a72qxkt] |
| ★ 8.4 Auto beat timeline from MusicXML | superseded by **3.6 Create timelines from MusicXML** (broader; from ClickUp) |
| ★ 9.2 Lyrics timeline | `New timeline: lyrics timeline` [CU:86a72qxj3] |

### ClickUp items that **stay in ClickUp** (not GitHub issue candidates)

These are tracked in Epic 13 (Engineering & refactor) and Epic 15 (View / UX polish)
as cluster summaries below. Suggest **not duplicating them as GitHub issues** unless
one is promoted to a feature.

### Important: meeting note typo

Meeting notes cite `#322` for "Do not require empty timeline for import"; the matching
issue is actually `#327`. Used `#327` below.

### In progress with no issue cited

**Persistent IDs** is in progress per the meeting notes but I couldn't find an issue or
draft for it on the project. Needs an issue/draft so the references chain (4.2–4.4)
can declare it as a dependency.

### Suggested labels

The project already uses `bug`, `enhancement`. Suggested additions:

- `epic` — for tracker / parent issues
- `score`, `harmony`, `hierarchy`, `import-export`, `properties`, `components`,
  `audio`, `selection`, `streaming`, `i18n`
- `ux`, `architecture`, `refactor`
- `needs-design` — when design is not yet settled
- `lcma` — optional; for LCMA-meeting features (only in GH if you want them
  filterable there too)

---

# Desktop

## EPIC 1 — Component label templating  ★

Origin: LCMA shortlist. Lightweight precursor to user-defined properties.

### ★ 1.1  Display component properties as part of the label  *[shortlist]*
- **Body**: Allow `{{property}}` template syntax in labels (e.g.
  `{{formal_function}}/{{formal_type}}`). Render basic markdown (bold, italics)
  using Qt's built-in features. Consider whether a `name` property is still needed.
- **Labels**: `enhancement`, `properties`, `components`
- **Suggested Immediacy**: 3
- **Blocks**: 2.1, 4.4

---

## EPIC 2 — Properties & templates (full)  ★

### ★ 2.1  User-defined properties
- **Body**: Typed properties per component, shown in inspector, referencable from
  label templates.
- **Labels**: `enhancement`, `properties`, `epic`
- **Depends on**: 1.1

### ★ 2.2  Computed properties (derived values)
- **Body**: Properties whose value is computed from other properties via the same
  template syntax used in labels.
- **Labels**: `enhancement`, `properties`
- **Depends on**: 2.1

### ★ 2.3  Component templates ("auto-complete")
- **Body**: Presets — e.g. PAC marker template, presentation hierarchy template.
  Seeds component properties and label format.
- **Labels**: `enhancement`, `components`
- **Depends on**: 2.1

---

## EPIC 3 — Score timeline (Verovio cluster)

Architectural change centred on `#506`. Verovio spike at `C:\Users\Felipe\dev\verovio`
and design proposal in `docs/design/score-viewer-verovio.md` are starting points.

### ★ 3.1  Verovio as a score engine — `#506` (existing)

### ★ 3.2  MEI support in score timeline
- Read MEI files directly. Use Verovio for ingestion and rendering.
- **Depends on**: `#506`

### ★ 3.3  Properly handle implicit measures (cadenzas) — `#273` (existing)

### ★ 3.4  Save note annotations to MEI
- **Depends on**: 3.2

### ★ 3.5  Version-controllable score-timeline save format
- **Depends on**: 3.2

### 3.6  Create timelines from MusicXML  *[from ClickUp]*  [CU:86a72qxgt]
- **Body**: Parent task in ClickUp with sub-tasks: research relevant MusicXML
  elements [CU:86a78nk7f], figure out logic of repeat types [CU:86a78nk7q], design
  user dialog [CU:86a78nk7u], implement data conversion [CU:86a78nk81], tests
  [CU:86a78nk89]. **Supersedes the meeting's "auto-generate beat timeline from
  musicXML" (8.4)** — keeps that as a sub-case.
- **Labels**: `enhancement`, `score`, `import-export`
- **Assignee**: Anne Foo (per ClickUp)
- **Depends on**: nothing structural; dovetails with `#506`

### 3.7  Score timeline polish (cluster — 3 sub-items)  *[from ClickUp]*
- **Body**: Three small score-timeline improvements that share file/test scope:
  - Show all measure numbers on vexflow [CU:86a7m55fv]
  - Export score image with annotations [CU:86a7m55kc]
  - Redo `vexflow get_beat` so score_tl isn't reliant on beat_tl [CU:86a7m56b6]
- **Labels**: `enhancement`, `score`
- **Open as**: 1 issue with 3 task-list items, or 3 separate issues — your call.

---

## EPIC 4 — Component relationships  ★

### ★ 4.1  Persistent IDs (in progress — no issue cited)
> **Confirm**: open an issue / project draft so 4.2–4.5 can declare it as a dep.

### ★ 4.2  References between components — `#334` (in props), `#340` (relations layer)
- **Depends on**: 4.1

### ★ 4.3  Link / Reuse component — `#341` (existing)  [CU:86a72qxu7]
- **Depends on**: 4.2

### ★ 4.4  Inline references in component text
- **Body**: Allow `{{ref:hash}}`-style references inline in label/text. Sits on
  label templating (1.1) and persistent IDs (4.1).
- **Depends on**: 1.1, 4.1

### ★ 4.5  Connectors in hierarchy  *[shortlist]*
- **Body**: Visual arcs connecting hierarchy components. Open question: new
  component type vs. repurpose Post-End / Pre-Start. Should be designed alongside
  `#340`.
- **Labels**: `enhancement`, `hierarchy`, `needs-design`
- **Related to**: `#340` (decide overlap before issuing)

---

## EPIC 5 — Hierarchy graphics  ★

### ★ 5.1  Overlapping ends in hierarchy components
### ★ 5.2  Different fill patterns / brush  [CU:86a72qxf7]
### ★ 5.3  Different shapes (triangle / oval / trapezoid / ...)
### ★ 5.4  Visual indicators for overlaps (BriFormer-style)

- One issue with sub-items, or four separate issues — your call.
- **Labels**: `enhancement`, `hierarchy`, `ux`

---

## EPIC 6 — Harmony

### ★ 6.1  Better chord input UI
### ★ 6.2  More chord types
### ★ 6.3  More flexible chord-text parsing — `#352` (existing)
### ★ 6.4  Better keyboard navigation in harmony timeline
### ★ 6.5  Display chord labels with less clutter

#### From ClickUp (extending Epic 6):

### 6.6  Harmony rendering: inversion accidentals + quality-symbol settings
- **Body**: Two related items — calculate inversion accidentals based on key
  [CU:86a72qxmk], and configurable quality symbols in settings file [CU:86a72qxh3].
- **Labels**: `enhancement`, `harmony`

### 6.7  Extend chord-text parsing — custom labels, mixed-case, tremolo
- **Body**: Three extensions to `#352`: `SelectHarmonyParams` custom-label support
  [CU:86a72qxr4], mixed-case roman parsing [CU:86a72qxty], tremolo parsing
  [CU:86a72qxg0].
- **Labels**: `enhancement`, `harmony`
- **Related to**: `#352`

### 6.8  Efficient beat-for-beat input (harmony) [CU:86a72qxt6]
- **Body**: Workflow improvement: enter harmony per beat fluently, without
  reaching for the mouse. Overlaps with 6.4 keyboard navigation.
- **Related to**: 6.4

### 6.9  Harmony tooltip on alternate text [CU:86a72qxf2]
- **Body**: Fix `HarmonyUI` alternate text so a tooltip can be implemented.
- **Labels**: `enhancement`, `harmony`, `ux`

---

## EPIC 7 — Beat & grid alignment

### ★ 7.1  Snap to metric grid — `#342` (existing)  [CU:86a72qxha]
### ★ 7.2  Command: align components to beat grid  *[shortlist]*
- **Open question**: should this replace `#342` or coexist?

### ★ 7.3  Align components to a new recording  [CU:86a72qxum overlaps]
- **Body**: Re-anchor existing components onto a new recording (warping).
- ClickUp's "Adjust component times according to CSV file" [CU:86a72qxum]
  overlaps but is the CSV-driven sub-case; consider as one issue.

### ★ 7.4  Automatic beat detection  *[scope?]*  [CU:86a72qxkt]

### 7.5  Snap to components  *[from ClickUp]*  [CU:86a72qxub]
- **Body**: Snap to component edges (distinct from snap-to-beats). Useful for
  aligning markers to existing hierarchy boundaries.

---

## EPIC 8 — Import / export / corpus

### ★ 8.1  Don't require empty timeline for import — `#327` (existing)
### ★ 8.2  CSV export for individual timelines  *[shortlist]*
### ★ 8.3  Tabs in TiLiA — paste-complete across files  *[scope?]*
### ★ 8.4  ~~Auto-generate beat timeline from MusicXML~~ → **superseded by 3.6**
### ★ 8.5  Corpus management

### 8.6  Improve import CSV dialog  *[from ClickUp]*  [CU:86a72qxqm]
- **Body**: UX overhaul of the CSV import dialog. Naturally bundles with `#327`.

---

## EPIC 9 — New timeline types  ★

### ★ 9.1  Graph Timeline (continuous values) — e.g. dynamics
### ★ 9.2  Lyrics timeline  [CU:86a72qxj3]

---

## EPIC 10 — Misc  ★

### ★ 10.1  UI for alternative analyses

---

# Desktop — extensions from team backlog

## EPIC 11 — Selection & keyboard navigation  *[ClickUp]*

A coherent UX cluster missing from the LCMA meeting input. Worth grouping into one
parent issue with sub-issues.

### 11.1  Ctrl + click for selection  [CU:86a72qxgc]
### 11.2  Shift + arrow / Shift + click selection  [CU:86a72qxfa, 86a72qxnr]
### 11.3  Vertical arrow selection (incl. harmony)  [CU:86a72qxvw, 86a72qxcz]
### 11.4  Box selection should ignore occluded units  [CU:86a72qxft]
### 11.5  Hand tool — middle-click drag  [CU:86a72qxvh]
### 11.6  Zoom to rectangle  [CU:86a72qxfn]

- **Labels**: `enhancement`, `selection`, `ux`

---

## EPIC 12 — Streaming & playback  *[ClickUp]*

### 12.1  Audio streaming services integration  [CU:86a72qxcj]
### 12.2  Movie streaming services integration  [CU:86a72qxqz]
### 12.3  Subtitle support for local video  [CU:86a72qxfe]
### 12.4  YouTube player fixes (3 items)
- Embedded YouTube links don't work [CU:86a72qxk6]
- YouTube auto-plays after loading [CU:86a72qxkx]
- Slider flashes back and forth [CU:86a72qxjd]

### 12.5  `QMediaPlayer` error display  [CU:86a74cahz]

- **Labels**: `enhancement`, `streaming`, `audio`

---

## EPIC 13 — Engineering & refactor  *[ClickUp — stay in ClickUp]*

Cluster summary — **don't create individual GitHub issues for these unless promoted.**
~17 items across:

- Drag method dedup (Marker / PDF / Harmony / Mode) [CU:86a72qxct]
- Deduplicate `_deselect_all_but_last` [CU:86a72qxd5]
- Timeline → facade [CU:86a72qxdd]
- `is_first_in_measure` → `ComponentManager` [CU:86a72qxe4]
- `.tla` structure aligned with web DB [CU:86a72qxe8]
- Rename `media length` → `duration` [CU:86a72qxf0]
- Single/double-click event method dedup [CU:86a72qxgj]
- CSV importer refactor [CU:86a72qxjn]
- Split `get_*` enum vs logic [CU:86a72qxjy]
- DragManager GC leak [CU:86a72qxm3]
- Refactor strings → constants [CU:86a72qxmb]
- Differentiate metadata-field types [CU:86a72qxnk]
- Rename `beats_in_measure` [CU:86a72qxny]
- BeatTimeline validation restrictions [CU:86a72qxq1]
- Split `post_*` enum vs logic [CU:86a72qxtp]
- Move from exceptions to success/result pattern [CU:86a72qxtu]
- Reuse `_add_harmony` template for fixtures [CU:86a72qxu5]
- Refactor beat timeline methods [CU:86a72qxw3]
- Tests for beat-altering measure changes [CU:86a72qxw9]

---

## EPIC 14 — Internationalization  *[ClickUp]*

### 14.1  Implement internationalization  [CU:86a72qxq9]
- **Labels**: `enhancement`, `i18n`, `epic`

---

## EPIC 15 — View / UX polish  *[ClickUp — stay in ClickUp unless promoted]*

Cluster summary — ~12 items:

- Multiple views per timeline kind [CU:86a72qxd8]
- Improve TL-to-TL data sharing [CU:86a72qxkh]
- Subtitle support has its own UX layer (already in 12.3)
- Show component info on hover [CU:86a72qxk3]
- Loading screen for slow ops [CU:86a72qxkc]
- Personalize delete-button tooltip [CU:86a72qxn5]
- Visual feedback for selected TL UI [CU:86a72qxpe]
- "Lock" timeline label to left of screen [CU:86a72qxrc]
- Labels overlap when zooming out [CU:86a72qxrg]
- Status bar [CU:86a72qxt0]
- Window auto-resize on file load [CU:86a72qxug]
- Time-in-measures unit in Inspect [CU:86a72qxur]
- Change beat pattern option on beat tl [CU:86a72qxmx]
- Automatic scene detection [CU:86a72qxeu]

---

# Web (TiLiA frontend + backend)

Tracked in ClickUp. **Open as GitHub issues only the items you actively want to
work in 0.x of the web app.** All have ClickUp IDs for back-reference.

## Web Frontend

### WF1 — Querying & search

- Add querying for PDF timeline (frontend) [CU:86a72qx13]
- Link source-file position on TL element query [CU:86a72qx1m]
- Link to source file on TL element query [CU:86a72qx1w] **(HIGH)**
- Add timeline-name column to results [CU:86a72qx98]
- `react-select` on explore-page dropdowns [CU:86a72qx43]
- `>`, `<`, `between` operators in TL queries [CU:86a72qxbh]
- Sequence querying [CU:86a72qx7t]
- Simple search (no field selection) [CU:86a72qx9z]
- Harmony query [CU:86a9xveq7]
- Querying multiple component types [CU:86a9xvgdj]
- Column hide/show on query tables [CU:86a72qxb2]

### WF2 — PDF / score viewer in browser

- Display IMSLP PDFs [CU:86a72qxa9]
- Broken layout when PDF fails to load [CU:86a72qxae]
- Buffer next PDF page [CU:86a72qxb7]
- Spinner replaces "Loading PDF…" text [CU:86a72qx4g]
- PDF ribbon overlap with user menu [CU:86a72qxbt]
- YouTube player aspect ratio matches video [CU:86a72qx9r]
- YouTube copyright disclaimer [CU:86a9g3ra1]

### WF3 — Profile / dashboard / pagination

- Set file title from dashboard [CU:86a72qx0j]
- Set composer from dashboard [CU:86a72qx20]
- Basic profile info [CU:86a72qx2z]
- Pagination on dashboard [CU:86a72qx4a]
- Ellipsis to hide excessive pagination links [CU:86a72qx2d]
- Spinner for user-files load [CU:86a72qx5r]
- Dashboard sorting [CU:86a72qx94]
- Split profile and "My files" page [CU:86a72qx8z]
- Rename "Dashboard" → "My account" [CU:86a72qxcf]
- Confirm overwrite when metadata identical [CU:86a72qx9g]

### WF4 — Wiki / metadata pages

- Wiki page for composers [CU:86a72qx7j]
- Wiki page for works [CU:86a72qxam]
- Page for analytical-corpus info [CU:86a72qx8k]
- `time` property on `PdfMarker` data [CU:86a72qxc2]

### WF5 — Help pages  *[cluster summary]*

7 items: PDF help [CU:86a7knrxg, 86a72qx26], score help [CU:86a7knryk, 86a72qxby],
audio-wave help [CU:86a72qx68], delete-toolbar gif update [CU:86a7y1v74], help-page
search [CU:86a72qx5f]. Group as one tracker issue.

### WF6 — UI / styling / layout polish  *[cluster summary]*

14 items: form appearance, file-viewer responsive, navbar limits, footer toolbars,
TL-name label wrapping, browse timeout, navbar stack on small screens, form
centering, redo explore styling, mouse-position zoom, dark mode, fit-to-screen
zoom, preserve visible TLs on zoom. Cluster lives in ClickUp; promote individual
items as needed.

### WF7 — Frontend engineering

- Reducer for tilia-viewer state [CU:86a72qx60]
- Naming convention for split CSS files [CU:86a72qx8u]
- Group media state into a single object [CU:86a72qxav] **(HIGH)**

---

## Web Backend

### WB1 — Upload handling
- File-size limit [CU:86a72qxwd]
- Handle missing file params (e.g. title) [CU:86a72qxwk]

### WB2 — Querying backend
- Querying for PDF timeline (backend) [CU:86a72qxx2]

### WB3 — Analytical corpus DB model
- DB model for analytical corpus [CU:86a72qxwz]

### WB4 — Email service config
- Change SendGrid account email to `tilia@tilia-app.com` [CU:86a72qxwr]

---

# Triage summary

| Bucket | Count | Notes |
|---|---:|---|
| LCMA features (★) — net-new GH issues | ~22 | Epics 1–10, minus already-existing issues |
| LCMA features — already issued | 8 | `#273`, `#327`, `#334`, `#340`, `#341`, `#342`, `#352`, `#506` |
| LCMA features — in progress | 1 | Persistent IDs (4.1) — no issue cited, **needs one** |
| LCMA features — done | 1 | CLI Documentation |
| ClickUp-only desktop **features** worth issuing | ~12 | Epics 6.6–6.9, 7.5, 8.6, 11.x, 12.x, 14, plus 3.6, 3.7 |
| ClickUp-only desktop **internal** (stay in ClickUp) | ~30 | Epics 13, 15 |
| Web Frontend (cluster) | 56 | Tracked in ClickUp; promote on demand |
| Web Backend | 5 | Few enough to issue all if you want |

## Decision points before opening anything

1. **Confirm 4.1 Persistent IDs** has an issue or open one — many other issues will
   cite it as a dependency.
2. **Decide 7.2 vs `#342`** scope (your shortlist note says one partly replaces
   the other).
3. **Decide whether 3.6 absorbs 8.4** entirely or coexists.
4. **Decide whether to mark items with `lcma` label** in the GitHub project, or
   leave that distinction to the drawio only (per your instruction).
5. **Confirm 8.3 (Tabs)** is in 0.6 scope at all — much larger than its peers.
6. **Web items**: which (if any) should be promoted from ClickUp to GH issues
   right now, vs. left as a backlog?
