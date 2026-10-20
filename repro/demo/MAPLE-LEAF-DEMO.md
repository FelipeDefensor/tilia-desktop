# Demo — score following on the Maple Leaf Rag

Scott Joplin's *Maple Leaf Rag* (1899) in TiLiA. The PDF score follows the
recording **measure by measure**, repeats included: the orange box jumps back
to measure 2 when the A section repeats, skips to the 2nd ending, and turns
the page at the Trio.

Everything is aligned **by construction**. Score, measure boxes and audio all
come from the same encoding, so there is no hand alignment to drift.

## Run it

```bash
cd ~/dev/tilia-pdf-bbox && uv run --python 3.12 tilia "$PWD/repro/demo/maple-leaf-rag.tla"
```

Put the *TiLiA PDF Viewer* window next to the main window. A tall, narrow
window works best, since the view scrolls only when the current measure would
leave it. Press play. If you're asked to save on quit, answer **No**.

What's in the file:

| Timeline | What it holds |
|---|---|
| **Form** (hierarchy) | A A B B A C C D D, grouped into *Part I* and *Trio* |
| **Measures** (beat) | 2/4, one beat per quarter, pickup as a 1-beat measure. Measure numbers follow the performance: 1, 2…17, 2…16, 18, 19…34, 19…33, 35, 36…67, 52…66, 68, 69…84, 69…83, 85 |
| **Score** (PDF) | 145 markers, one per *performed* measure, each pointing to its measure's box. Made by *Timelines → PDF → Import measure regions from MEI* from `maple-leaf-rag-zones.mei` |

## Talking points for the demo

1. **Press play.** The box walks through measures 1–17 while the hierarchy
   shows the first A.
2. **At 0:21, after the 1st ending (m. 17),** the box jumps back to m. 2: the
   beat timeline says the next measure is 2 again, and the importer gave
   measure 2 a marker for both passes.
3. **At 0:41** it skips from m. 16 straight to the 2nd ending, m. 18.
4. **At the Trio (1:45, m. 52)** the view moves to page 2's last system.
   Everything is driven by the same marker list, no extra page markers.
5. **Click any marker** in the Score timeline, or any section in Form: the
   playhead jumps, and the box follows.
6. **Draw** a new box with the mouse on any measure. It becomes a marker at
   the playhead, the same prototype feature as in `PDF-REGION-REPRO.md`.
7. **The point for Amichay:** the boxes came in as an *MEI facsimile*, the
   format Cartographer exports. A segmentation tool (NoghenOMR, Cartographer
   with its Measure Detector, anything else) only has to write measure zones.
   TiLiA times them with the beat timeline.

## Files

| File | What it is |
|---|---|
| `maple-leaf-rag.tla` | The demo. Built by `build_maple_leaf_demo.py`. Stores **absolute** paths to the PDF and MP3. |
| `maple-leaf-rag.pdf` | 3 A4 pages, engraved by Verovio from the source encoding. |
| `maple-leaf-rag.mp3` | 3:11, 192 kbit/s. Piano (General MIDI program 0, macOS's built-in `gs_instruments.dls`), light hall reverb, loudness-normalised to −16 LUFS. All repeats played; ♩ = 92 with a ritardando over the last two measures. |
| `maple-leaf-rag-zones.mei` | Cartographer-style MEI: 3 `<surface>`s (as for 300 dpi scans) with 85 measure `<zone>`s. |
| `score.json`, `performance.json` | Intermediate data: the engraving (measures and notes) and the performance (measure starts and note events). |
| `source/Joplin_Maple_leaf_Rag.mei` | Source encoding, unchanged. From [music-encoding/sample-encodings](https://github.com/music-encoding/sample-encodings) (`MEI_5.0/Music/Complete_examples/`), ECL-2.0. Encoded by Maja Hartwig and Kristina Richts, Musikwissenschaftliches Seminar Detmold, 2011. The music is in the public domain. |
| `pipeline/` | The scripts that made the files above (below). |
| `build_maple_leaf_demo.py` | Builds the `.tla` through user commands (`timeline.beat.add`, `…set_amount_in_measure`, `…set_measure_number`, `timelines.add.pdf`, `timelines.import.pdf_mei`, `timeline.hierarchy.add`) and `file.save_as`. |
| `test_maple_leaf_demo.py` | Headless checks (S0c). |

## S0c — Headless checks

```bash
uv run --python 3.12 python -m pytest -p tests.conftest -p no:xdist repro/demo/test_maple_leaf_demo.py -v
```

Expected: `5 passed`. Covers:

- the media and PDF paths exist
- the beat timeline's measure numbers match the performance
- 145 markers over 3 pages
- both passes of m. 2 share a box
- **every one of the 145 performed measures is fully on screen** when playback
  reaches it, in an 820 × 480 viewer

## How it was made (pipeline)

Run from `repro/demo/`. Steps 1 and 4 need tools outside TiLiA's
environment: Verovio from PyPI, and Swift and ffmpeg, which are already on
this Mac.

1. **Engrave.** Verovio 6.3 lays out the score on A4 and dumps per-page SVG,
   measure starts and every note's onset/offset in quarters
   (`renderToTimemap`, `getMIDIValuesForElement`):
   ```bash
   uv run --with verovio --python 3.12 python -I pipeline/render.py source/Joplin_Maple_leaf_Rag.mei build
   ```
2. **PDF and zones.** Qt's SVG renderer is SVG Tiny 1.2, so the script first
   flattens Verovio's nested `<svg>` (into a scaled `<g>`) and nested `<tspan>`s,
   then draws each page as vectors onto a `QPdfWriter` page, adding the title.
   Measure zones come from Verovio's geometry: staff lines give the width,
   top-to-bottom staff gives the height, plus 1.5 staff spaces.
   ```bash
   uv run --python 3.12 python -I pipeline/prepare_score.py build maple-leaf-rag.pdf maple-leaf-rag-zones.mei
   ```
3. **Performance.** Plays the form out (pickup; A A with 1st/2nd endings; B B;
   A; C C; D D: 145 measures) at ♩ = 92 and writes note events:
   ```bash
   python3 -I pipeline/perform.py build 92
   ```
4. **Audio.** AVAudioEngine in offline rendering mode with an
   AVAudioUnitSampler on the GM bank, events applied between 64-frame
   renders (about 1.5 ms timing), then loudness-normalised MP3:
   ```bash
   swift pipeline/synth.swift build/performance.json build/maple-leaf-rag.wav
   ffmpeg -i build/maple-leaf-rag.wav -af loudnorm=I=-16:TP=-1.5 -ar 44100 -b:a 192k maple-leaf-rag.mp3
   ```
   `pipeline/check_audio.py` checks the alignment. Energy in the 25 ms after
   each planned onset vs the 25 ms before: median **2.4×** on the planned
   onsets, **0.83×** half a sixteenth later (the control).
5. **Assemble.** `build_maple_leaf_demo.py` (above).

The commands here are the equivalents of what was run. The pipeline actually
ran from a scratch folder with its own venv, and step 4 ran a compiled
`swiftc -O` binary.

## Limits — say these out loud

- **Engraved, not scanned.** The PDF is a Verovio engraving, so the boxes are
  exact. A scanned edition needs measure zones from a person (Cartographer) or
  a detector (Measure Detector, NoghenOMR). The import path is the same.
- **Synthesised, not recorded.** It's a General MIDI piano at a steady tempo,
  with no rubato or swing. A real recording needs the beat timeline tapped or
  aligned to it, and then the same import gives a box per measure again.
- **Text simplification.** Collapsing `<tspan>`s keeps each text's last style,
  so a text mixing styles (none visible in this score) would be rendered in
  one style.
