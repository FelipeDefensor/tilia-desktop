# Repro bundle — PDF marker regions (bounding boxes) and MEI import

Branch: `feat/pdf-marker-bbox`, worktree `~/dev/tilia-pdf-bbox`. Base:
`upstream/dev`. Regions are commit `494e0737`, the MEI import `a30e05dc`, the
scroll fix (scroll only when the region is off-screen) `7f149f7f`.

**Demo on a real piece:** [`demo/MAPLE-LEAF-DEMO.md`](demo/MAPLE-LEAF-DEMO.md)
is the Maple Leaf Rag with audio and 145 measure boxes, repeats included.

A PDF marker can now point to a **region** of a page (`bbox = [x, y, w, h]`,
relative to the page size) instead of only to a whole page. This is the TiLiA
side of importing NoghenOMR's system/measure segmentation. Markers without a
region keep pointing to the whole page, so older files load unchanged.

- **Draw:** left-drag in the PDF viewer. If exactly one marker is selected it
  gets the region. Otherwise the marker at the playhead gets it, and if there
  is none, a marker is created at the playhead (`timeline.pdf.set_region`).
- **Play:** every region is outlined in blue. The current marker's region is
  filled orange. When the current marker changes and its region isn't fully
  visible, the viewer scrolls so the region sits at the top. If it is
  visible, the view stays put, so following measures within one system
  doesn't jiggle the page.
- **Clear:** marker context menu → *Clear PDF region* (`timeline.pdf.clear_region`).
- **Inspect:** the inspector has a *Region* row ("86% × 12% at (7%, 9%)" or
  "Whole page").
- Copy/paste, undo/redo and save/reopen carry the region.
- **Import from MEI:** Timelines → PDF → *Import measure regions from MEI
  (Cartographer)* (`timelines.import.pdf_mei`). Reads the measure zones that
  the [Cartographer App](https://github.com/Edirom/cartographer-app) exports and
  replaces the PDF timeline's markers with one per measure. The beat timeline
  gives each measure's time (one marker per pass for repeated measure numbers),
  the zone's surface gives the page (n-th surface = n-th PDF page), and the zone
  itself becomes the region, relative to the image size.

## Files

| File | What it is |
|---|---|
| `repro/score.pdf` | Stand-in score: 2 A4 pages, 4 systems per page, every system a 5-line staff with 4 measures and a "System N" label. Generated, so no copyrighted score is involved. |
| `repro/pdf-region.tla` | Fixture. Media-free (100 s length, no media file). One PDF timeline, **Score**, on `score.pdf` with 8 markers, one per system, every 10 s from 0 to 70 s (systems 1–4 on page 1, 5–8 on page 2). Each marker's region frames its system. |
| `repro/score-zones.mei` | What Cartographer would export for `score.pdf` scanned at A4/300 dpi (2480 × 3508 px): 2 surfaces, 32 measure zones, measures numbered 1–32 in one movement. |
| `repro/pdf-mei.tla` | Starting point for the import. A PDF timeline **Score** on `score.pdf` (only the default whole-page marker) and a 4/4 beat timeline **Measures** with 32 measures of 2.5 s (measure *n* starts at (*n* − 1) × 2.5 s). |
| `repro/cartographer-sample.mei` | Cartographer's own test file (`public/testfile.xml`, MIT licence), unchanged. A Beethoven manuscript: 120 surfaces, zones only on surfaces 5 (22 measures) and 6 (44 measures), 66 measures. |
| `repro/build_pdf_region_fixture.py` | Regenerates `score.pdf`, `pdf-region.tla`, `score-zones.mei` and `pdf-mei.tla`. Draws the PDF with `QPdfWriter`, then runs the real app headless through user commands and saves with `file.save_as`, so the `.tla` JSON is never hand-written. The MEI *is* written by hand on purpose, since it stands in for another program's output. |
| `repro/test_pdf_region_feature.py` | Headless acceptance checks for regions against `pdf-region.tla` (S0). |
| `repro/test_mei_import_feature.py` | Headless acceptance checks for the MEI import against `pdf-mei.tla` and the Cartographer sample (S0b). |

Regenerate the fixtures. The `.tla` files store `score.pdf`'s **absolute
path**, so rebuild them after moving the folder:

```bash
uv run --python 3.12 python -m pytest -p tests.conftest -p no:xdist repro/build_pdf_region_fixture.py -q
```

## S0 — Headless acceptance checks

```bash
uv run --python 3.12 python -m pytest -p tests.conftest -p no:xdist repro/test_pdf_region_feature.py -v
```

- **`feat/pdf-marker-bbox`:** `15 passed`.
- **`dev`:** `15 errors`, `set_region command not registered (are you on dev?)`.
  That confirms the feature doesn't exist there.

The checks cover:

- the fixture loading with all 8 regions
- playback highlighting the right system and page, for every system
- drawing a region at the playhead (new marker), and for a selected marker
- click without drag
- clearing from the context menu
- save and reopen
- a file from before the feature (no `bbox` key) loading as whole-page markers
- undo/redo for every change

Unit tests are in `tests/ui/timelines/pdf/test_pdf_region_ui.py`.

## S0b — Headless acceptance checks, MEI import

```bash
uv run --python 3.12 python -m pytest -p tests.conftest -p no:xdist repro/test_mei_import_feature.py -v
```

- **`feat/pdf-marker-bbox`:** `9 passed`.
- **`dev`:** `9 errors`, `MEI import command not registered (are you on dev?)`.

The checks cover:

- one marker per measure at the beat timeline's measure times
- pages split 16/16
- the region of measures 1 and 6 matching their zones
- playback highlighting measures 1, 6, 17 and 32
- undo/redo of the whole import
- Cartographer's real file: 22 markers on page 5 of a 5-page PDF, and the 44
  measures on surface 6 reported as beyond the PDF

Unit tests are in `tests/parsers/mei/test_pdf_from_mei.py`.

> Running plain `pytest` (no path) from the worktree also collects `repro/`,
> where the tests error because `tests/conftest.py` doesn't apply. Run
> `pytest -n auto tests` for the suite. The same applies to the `repro/`
> folder in the main checkout.

## GUI scenarios

Launch from the worktree with an absolute path. Outside `ENVIRONMENT=prod`,
`setup_dirs` chdirs into the `tilia` package after the argument has been parsed.

```bash
cd ~/dev/tilia-pdf-bbox && uv run --python 3.12 tilia "$PWD/repro/pdf-region.tla"
```

The PDF viewer opens in its own window, *TiLiA PDF Viewer*. Put it next to
the main window. If you're asked to save on quit, answer **No** so the fixture
stays clean.

### S1 — Playback follows the systems
- **Do:** press play (or click the time ruler at 5 s, 15 s, … 75 s).
- **Expected:** System 1's box is orange at 0–10 s, System 2's at 10–20 s, and
  so on. At 40 s the viewer jumps to page 2 with System 5 near the top. All
  other boxes stay blue outlines.

### S2 — Draw a region for a new marker
- **Do:** click empty space in the PDF timeline so nothing is selected. Click
  the ruler at **85 s**. In the viewer, drag a rectangle around measures 1–2 of
  System 3.
- **Expected:** a dashed rectangle follows the mouse while you drag. On
  release a marker appears at 85 s (page 1), its box is drawn and it's orange
  because it is now the current marker.

### S3 — Redraw a selected marker's region
- **Do:** click marker **20 s** (System 3) in the timeline. Drag a smaller
  rectangle around System 3's last measure.
- **Expected:** no new marker. System 3's box shrinks to the new rectangle.
  Selection decides the target, not the playhead.

### S4 — Drag past the page edge
- **Do:** start a drag inside page 1 and release it far to the right, outside
  the page.
- **Expected:** the region is clipped at the page's right edge.

### S5 — Clicks don't draw
- **Do:** single-click inside the viewer, and also drag starting in the grey
  space between pages.
- **Expected:** nothing changes.

### S6 — Clear a region
- **Do:** right-click marker **30 s** → *Clear PDF region*.
- **Expected:** System 4's box disappears. Seeking to 35 s shows page 1 again
  with no orange box.

### S7 — Inspector
- **Do:** click marker **0 s** and press **Enter**.
- **Expected:** the *Region* row reads **86% × 12% at (7%, 9%)**. After S6,
  marker 30 s reads **Whole page**.

### S8 — Undo / redo
- **Do:** after S2, S3 or S6, press **Ctrl+Z**, then **Ctrl+Shift+Z**.
- **Expected:** one undo step per drawn or cleared region. The boxes update
  immediately both ways.

### S9 — Copy / paste
- **Do:** select marker **0 s**, press **Ctrl+C**. Select marker **50 s**,
  press **Ctrl+V**.
- **Expected:** marker 50 s takes marker 0's page *and* region. It now points
  to System 1 on page 1.

### S10 — Resize the viewer window
- **Do:** make the viewer much wider than the page, then narrower than it.
- **Expected:** the boxes stay on their systems. When the window is wider the
  page is centered, and the boxes move with it.

### S11 — Save and reopen
- **Do:** after drawing a region, **File → Save As** to a temp file, close it,
  then reopen it.
- **Expected:** all regions come back.

### S12 — Import measure regions from MEI
- **Do:** open `repro/pdf-mei.tla` instead:
  ```bash
  cd ~/dev/tilia-pdf-bbox && uv run --python 3.12 tilia "$PWD/repro/pdf-mei.tla"
  ```
  Then go to **Timelines → PDF → Import measure regions from MEI
  (Cartographer)**, answer **Yes** to replacing the existing marker, and pick
  `repro/score-zones.mei`.
- **Expected:** no dialog. The PDF timeline shows 32 markers, one every 2.5 s
  in line with the beat timeline's measures. The viewer outlines all 16
  measures on page 1.

### S13 — Score following, measure by measure
- **Do:** after S12, press play (or click the ruler at 1 s, 3.5 s, 6 s, …).
- **Expected:** the orange box moves one measure every 2.5 s, left to right
  and system by system. At 40 s (measure 17) the viewer jumps to page 2.

### S14 — Measure times follow the beat timeline
- **Do:** after S12, in the beat timeline select a beat of measure 3 and
  set its measure number to **1** (context menu → *Set measure number*). Then
  import `score-zones.mei` again.
- **Expected:** the beat timeline now numbers its measures 1, 2, 1, 2, 3, …, 30,
  so measures 1 and 2 each get two markers, one per pass, and the viewer
  highlights System 1's first two boxes again at 5 s. The import finishes with
  a dialog listing "No measure with number 31" and "… 32", because the
  renumbered beat timeline no longer reaches them.

### S15 — Cartographer's own file (partial import)
- **Do:** add a PDF timeline on `tests/resources/example.pdf` (5 pages) and
  make sure the beat timeline has at least 22 measures. Import
  `repro/cartographer-sample.mei`.
- **Expected:** a dialog reports the import finished with errors: 44 lines of
  "Measure N: on page 6, but the PDF has 5 pages." 22 markers are created on
  page 5. `example.pdf` isn't that manuscript, so the boxes don't match its
  content. The point is that real Cartographer output parses.

### S16 — Failed import leaves the timeline as it was
- **Do:** run the import and pick a file that isn't MEI, e.g. `score.pdf` or
  a MusicXML file.
- **Expected:** "Import failed" dialog (*Can't read MEI file* or *Not an MEI
  file*), and the PDF markers from before are still there.

## Known gaps (prototype)

- **MEI: one movement.** Measure numbers restart in each `<mdiv>`, but the
  beat timeline numbers measures once per file, so only the first movement is
  imported and a warning names it. A movement picker would fix this.
- **MEI: page mapping by position.** The n-th `<surface>` is taken as the
  n-th PDF page. If the PDF has extra pages (a cover the images don't have),
  everything is off by that many pages. An offset option would fix this.
- **MEI: split measures.** A measure across a system break has several zones.
  Only the first, where the measure starts, becomes the region.
- **MEI: no Cartographer round trip.** Importing only. Regions drawn in TiLiA
  can't be exported back to MEI yet.

- **Dragging a marker in time** doesn't refresh which box is orange until
  playback or a seek changes the current time. Page switching has always
  worked this way, so it's inherited, not new.
- **No NoghenOMR import yet.** The plan is to import the JSON it produces, one
  box per system or measure, as `timeline.pdf.add` calls with `bbox`.
- **No zoom UI.** TiLiA doesn't expose zoom for the PDF viewer. The layout
  maths does handle `zoomFactor`, which was checked against rendered pixels at
  1.0 and 1.5.
- **Layout is reproduced, not queried.** `QPdfView` doesn't expose page
  geometry, so `QPdfWindow.page_rect()` mirrors Qt's layout: pages stacked
  vertically, scaled by screen DPI × zoom, centered horizontally. A Qt upgrade
  that changes the layout would misplace the boxes. S10 is the check to rerun.

## Cleanup

`repro/` is untracked, so it survives branch switches. Delete the folder once
the feature has merged.
