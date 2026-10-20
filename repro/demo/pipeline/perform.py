"""Plan a performance of the Maple Leaf Rag with its repeats played out.

Reads score.json (from render.py) and writes, next to it:
- performance.json   performed measures in order: notated index, start (s),
                     length (s); and note events [onset s, pitch, velocity, length s]

Form (measure indices, as in the MEI): pickup 1; A 2–17 with 1st ending 17 and
2nd ending 18; B 19–34, endings 34/35; A again written out 36–51; Trio C 52–67,
endings 67/68; D 69–84, endings 84/85.

Usage: python -I perform.py RENDER_DIR [quarter_bpm]
"""

import json
import random
import sys
from pathlib import Path

render_dir = Path(sys.argv[1])
bpm = float(sys.argv[2]) if len(sys.argv) > 2 else 92.0
score = json.loads((render_dir / "score.json").read_text())
measures = {m["index"]: m for m in score["measures"]}


def span(first: int, last: int) -> list[int]:
    return list(range(first, last + 1))


ORDER = (
    [1]
    + span(2, 17)
    + span(2, 16)
    + [18]  # A A
    + span(19, 34)
    + span(19, 33)
    + [35]  # B B
    + span(36, 51)  # A
    + span(52, 67)
    + span(52, 66)
    + [68]  # C C
    + span(69, 84)
    + span(69, 83)
    + [85]  # D D
)

notes_by_measure: dict[int, list[dict]] = {}
for note in score["notes"]:
    notes_by_measure.setdefault(note["measure"], []).append(note)

seconds_per_quarter = 60.0 / bpm
rng = random.Random(1899)  # a touch of velocity variation, reproducibly
performed, events = [], []
time = 0.0
for position, index in enumerate(ORDER):
    measure = measures[index]
    # Slow down over the last two measures so the piece doesn't stop dead.
    stretch = {len(ORDER) - 2: 1.12, len(ORDER) - 1: 1.35}.get(position, 1.0)
    quarter = seconds_per_quarter * stretch
    length = measure["length"] * quarter
    performed.append(
        {"index": index, "start": round(time, 4), "length": round(length, 4)}
    )

    for note in notes_by_measure.get(index, []):
        onset = time + (note["on"] - measure["start"]) * quarter
        duration = (note["off"] - note["on"]) * quarter
        if position == len(ORDER) - 1:
            duration += 1.2  # let the final chord ring
        left_hand = note["pitch"] < 60
        velocity = (70 if left_hand else 84) + rng.randint(-4, 4)
        events.append(
            [
                round(onset, 4),
                note["pitch"],
                velocity,
                round(max(duration * 0.95, 0.05), 4),
            ]
        )
    time += length

events.sort()
(render_dir / "performance.json").write_text(
    json.dumps(
        {
            "bpm": bpm,
            "duration": round(time + 2.5, 3),  # room for the last chord and reverb
            "measures": performed,
            "events": events,
        }
    )
)
print(f"{len(performed)} measures performed, {len(events)} notes, {time:.1f} s")
