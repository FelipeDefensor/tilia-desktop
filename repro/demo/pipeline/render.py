"""Engrave an MEI score with Verovio and dump what the demo needs.

Writes to OUT_DIR:
- page-N.svg      one SVG per engraved page
- score.json      measures (index, xml:id, @n, start and length in quarters)
                  and notes (pitch, onset and offset in quarters, measure index)

Usage: python -I render.py SCORE.mei OUT_DIR
"""

import json
import sys
from pathlib import Path

import verovio

score_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)

tk = verovio.toolkit()
tk.setOptions(
    {
        "pageWidth": 2100,  # A4, in tenths of a millimetre
        "pageHeight": 2970,
        "pageMarginTop": 260,  # room for the title prepare_score.py draws
        "pageMarginBottom": 80,
        "pageMarginLeft": 80,
        "pageMarginRight": 80,
        "scale": 40,
        "adjustPageHeight": False,
        "breaks": "auto",
        "footer": "none",
        "header": "auto",
    }
)
assert tk.loadFile(str(score_path)), "Verovio could not load the score"

page_count = tk.getPageCount()
for page in range(1, page_count + 1):
    (out_dir / f"page-{page}.svg").write_text(tk.renderToSVG(page))

timemap = tk.renderToTimemap({"includeMeasures": True, "includeRests": False})
last_qstamp = timemap[-1]["qstamp"]

measure_starts = [(e["measureOn"], e["qstamp"]) for e in timemap if "measureOn" in e]
mei = tk.getMEI()

measures = []
for index, (measure_id, start) in enumerate(measure_starts, start=1):
    end = measure_starts[index][1] if index < len(measure_starts) else last_qstamp
    measures.append(
        {
            "index": index,
            "id": measure_id,
            "page": tk.getPageWithElement(measure_id),
            "start": start,
            "length": end - start,
        }
    )

# Onset/offset of every note, in quarters, from the timemap.
onsets, offsets = {}, {}
for entry in timemap:
    for note_id in entry.get("on", []):
        onsets[note_id] = entry["qstamp"]
    for note_id in entry.get("off", []):
        offsets[note_id] = entry["qstamp"]


def measure_of(qstamp: float) -> int:
    current = 1
    for m in measures:
        if m["start"] <= qstamp:
            current = m["index"]
        else:
            break
    return current


notes = []
for note_id, on in onsets.items():
    midi = tk.getMIDIValuesForElement(note_id)
    if not midi or "pitch" not in midi:
        continue
    off = offsets.get(note_id, on + 0.25)
    notes.append(
        {
            "id": note_id,
            "pitch": midi["pitch"],
            "on": on,
            "off": off,
            "measure": measure_of(on),
        }
    )

(out_dir / "score.json").write_text(
    json.dumps({"pages": page_count, "measures": measures, "notes": notes}, indent=1)
)
print(f"{page_count} pages, {len(measures)} measures, {len(notes)} notes")
print("pages per measure:", {m["page"] for m in measures})
