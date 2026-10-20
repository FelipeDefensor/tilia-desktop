"""Sanity-check the rendered WAV against the planned note onsets.

For each planned onset, compares the energy in the 25 ms after it with the
25 ms before it. Rendered on time, attacks make the ratio clearly > 1. The same
measure at onsets shifted by half a sixteenth acts as a control.
Usage: python -I check_audio.py performance.json audio.wav
"""

import array
import json
import math
import sys
import wave

performance = json.load(open(sys.argv[1]))
with wave.open(sys.argv[2]) as w:
    rate, channels = w.getframerate(), w.getnchannels()
    samples = array.array("h", w.readframes(w.getnframes()))
mono = samples[::channels]
print(f"{len(mono) / rate:.1f} s at {rate} Hz")

peak = max(abs(s) for s in mono)
rms = math.sqrt(sum(s * s for s in mono[::50]) / len(mono[::50]))
print(f"peak {peak / 32768:.2f} FS, rms {20 * math.log10(rms / 32768):.1f} dBFS")


def energy(start: float, length: float) -> float:
    a, b = int(start * rate), int((start + length) * rate)
    chunk = mono[max(a, 0) : max(b, 0)]
    return sum(s * s for s in chunk) / max(len(chunk), 1)


def attack_ratio(offset: float) -> float:
    ratios = []
    for onset, *_ in performance["events"][::7]:
        t = onset + offset
        before, after = energy(t - 0.025, 0.025), energy(t, 0.025)
        if before > 0:
            ratios.append(after / before)
    ratios.sort()
    return ratios[len(ratios) // 2]


sixteenth = 60 / performance["bpm"] / 4
print(f"median attack ratio on planned onsets: {attack_ratio(0):.2f}")
print(f"median attack ratio half a 16th late:  {attack_ratio(sixteenth / 2):.2f}")
