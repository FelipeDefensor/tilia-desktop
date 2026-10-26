# Repro — schema builder (prototype 1)

Branch `feat/schema-builder` (worktree `~/dev/tilia-schema-builder`), off
`upstream/dev` (`daba826f`).

NoghenMadid's schema creator, in TiLiA's score viewer: a library of schemata
(stages × upper / inner / bass voices, degrees 1–7 with alterations), an
editor for them, and a palette whose degree circles you drag onto noteheads.
Each occurrence is a **schema instance** on the score timeline, saved in the
`.tla` with its own copy of the schema. It is drawn on the score in bands
above and below the staves, so the notes stay readable, and as a bar in a
schema lane under the score timeline's staves.

## Files

| File | What it is |
|---|---|
| `galant-phrase.musicxml` | Six measures, two voices, C major: Romanesca (stepwise) mm. 1–2, Prinner mm. 3–4, Do-Re-Mi mm. 5–6, one stage per half note. |
| `build_schema_fixture.py` | Builds `schema.tla` through user commands: beat timeline, `timelines.add.score`, `timelines.import.score` (real OSMD drawing, needs a connection), then every degree with `timeline.score.add_schema_degree`, then `file.save_as`. |
| `schema.tla` | The fixture: three instances, 22 placed degrees. No media; the timelines run 14.4 s. |
| `test_schema_feature.py` | Headless acceptance checks (S0). |

Rebuild the fixture:

```bash
uv run --python 3.12 python -m pytest -p tests.conftest -p no:xdist repro/build_schema_fixture.py -q
```

## S0 — Headless checks

```bash
uv run --python 3.12 python -m pytest -p tests.conftest -p no:xdist repro/test_schema_feature.py -v
```

- **On `feat/schema-builder`:** `13 passed`.
- **On `dev`:** every test errors with `no schema instance component (are you on dev?)` (checked with 11 tests, before the two lane and layout checks were added).

It covers:

- the three instances load
- each degree sits on the right notehead (staff and half-note column), with the right value
- all 22 degrees are drawn, with one line per voice per instance
- no circle or line covers the staves, and each marked note has a ring around it
- the schema lane shows the three instances as bars at the right times, in one row
- the toolbar button opens the palette
- a drop starts a new instance (with undo)
- clicking a degree continues its instance
- Shift+click removes a degree (with undo)
- New… in the palette saves a custom schema
- saving and reopening keeps everything

## GUI scenarios

Open the fixture:

```bash
cd ~/dev/tilia-schema-builder && uv run --python 3.12 tilia "$PWD/repro/schema.tla"
```

If asked to save on quit, answer **No**, unless you want your changes kept.

**S1 — See the annotations.** The Score Viewer shows the phrase.
- **Bands:** upper-voice degrees are black circles in a band above the staves, and bass degrees are white circles in a band below. Each circle stands at its note's x.
- **Rings:** each marked notehead has a thin ring in its instance's colour. With several instances on one note, the rings are concentric.
- **Rows:** circles of one instance are joined voice by voice, and its name is above. Instances that would collide take separate rows. Here Prinner's upper row sits above Romanesca's, because the name "Romanesca (stepwise)" reaches it.

**S1b — The schema lane.** Under the Score timeline's staves there is a lane with one bar per instance (Romanesca, Prinner, Do-Re-Mi), coloured like the schema, from its first note's start to its last note's end. Overlapping instances take separate rows, and the lane grows with them. Without instances, there's no lane. Clicking a bar selects it, seeks to its start, scrolls the score viewer to it and makes it the instance that drops go to. If measures repeat, an instance has one bar per pass.

**S2 — Open the palette.** Click **Schemata** at the bottom of the viewer's left toolbar. The panel on the right lists the library (Do-Re-Mi … Romanesca), with New…, Edit… and Reset/Delete, and the selected schema's stage diagram.

**S3 — Continue an instance.** Click any Prinner circle. The palette switches to Prinner and says "Adding to Prinner: 8 of 8 degrees placed". The placed degrees have a dark ring in the diagram.

**S4 — Drag a degree.** Pick **Meyer** in the palette. The Prinner instance is finished, and the label says to drag a degree. Drag the Meyer "1" (upper row) onto the last treble note. While you drag, a blue box shows the notehead it will land on. Drop it: a new Meyer instance appears, with "1 of 8 degrees placed". It gets a new row above the staves, a ring on the note, and a bar in a second row of the lane, since it overlaps Do-Re-Mi. Drag the other circles onto other notes, and they join the same instance. Dragging a circle that's already placed onto another note moves it.

**S5 — Remove.**
- **Shift+click** a circle to remove that degree.
- **Select** circles (click, or Ctrl+click for several) and press **Delete**.
- **Delete instance** in the palette removes the active instance.
- Removing an instance's last degree removes the instance.

Every step can be undone (Ctrl+Z) and redone.

**S6 — New schema.** Click **New…**. Give it a name and a family, then add stages and degrees: each degree has its number, its alteration (↑ ↓ ♮) and an optional register. The diagram below shows it as you edit. Save is greyed out until it has a name and every stage has a degree, and a name already in the library is refused. After saving, it's selected in the palette, ready to drag. Editing a starter schema and saving it under the same name overrides that starter, and the button then reads **Reset** to bring the starter back.

**S7 — Persistence.** Save, quit and reopen: instances and circles are back. An instance keeps the schema it was made with, even if you later edit that schema in the library or open the file on a computer without it. In that case the palette lists it as "(from file)".

**S8 — Jump.** Double-click a circle: playback seeks to that note, as double-clicking a note does.

## How it maps to NoghenMadid

The details come from NoghenMadid's public frontend bundle. Its repo is still private, and its schema library needs a sign-in, which wasn't used.

| NoghenMadid | TiLiA prototype |
|---|---|
| Schema JSON `{name, variant_of, variant_short, color, stages[{strength, upper/inner/lower[{value, accidental, relH, voice}]}]}` | Same format (`tilia/timelines/score/schema.py`), so definitions can move between the apps. |
| "Create Custom Schemata" editor | `SchemaEditor` (`tilia/ui/schema/editor.py`). |
| "Schemata Marker" window, stage diagram, drag circles onto `g.vf-notehead` | `SchemaPalette` docked in the score viewer, and `SchemaDiagram`. Both apps draw with OSMD, so the SVG classes are the same. |
| Annotation `notes_coord[{…, degree}]` | `SchemaInstance.degrees[{notehead, stage, voice, index, value, accidental}]`. It also records **which stage** each note fills, which NoghenMadid doesn't keep. |
| Private / public schemata on a server | Starter set plus the user's own schemata in the TiLiA settings. Files carry their own copies. |

## Known gaps — say these out loud

- **Starter schemata need checking.** The nine definitions, after Gjerdingen (2007), were written from memory: Do-Re-Mi, Fenaroli, Fonte, Meyer, Monte, Prinner, Quiescenza, and Romanesca stepwise and leaping. Fenaroli and Quiescenza especially should be checked by a theorist.
- **No alteration palette yet.** NoghenMadid's ↑ ↓ N ♮ chips change a placed degree. Here the alteration comes from the schema. The data model stores it per placement, so only the UI is missing.
- **Lane times come from the drawing.** An instance has no time of its own. Its bars run from the beat its first note is drawn at to the end of the longest note starting at its last note's beat. They update when the beat timeline loads or its measure numbers change, but not when beats are moved. There's no inspector for instances yet.
- **Noteheads are tied to the drawing.** Degrees are tied to notehead ids that TiLiA writes into the saved SVG. Re-importing the score clears the timeline anyway, but linking each degree to its `Note` component as well would make it sturdier.
- **Placement.** The bands make the scene taller, so the score viewer zooms out a little to fit. Several degrees of one voice in a stage, placed on one chord, sit side by side.
- The fixture needs OSMD from cdn.jsdelivr.net to be rebuilt, as any score import does.
