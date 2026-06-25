#!/usr/bin/env python3
"""Generate and play deterministic Twinkle test phrases for BandToy."""

from __future__ import annotations

import argparse
import math
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path


SAMPLE_RATE = 24000
BPM = 96
BEAT_SECONDS = 60.0 / BPM

NOTE_MIDI = {
    "C4": 60,
    "D4": 62,
    "E4": 64,
    "F4": 65,
    "G4": 67,
    "A4": 69,
}

PHRASES = {
    "phrase_1": [("C4", 1), ("C4", 1), ("G4", 1), ("G4", 1), ("A4", 1), ("A4", 1), ("G4", 2)],
    "phrase_2": [("F4", 1), ("F4", 1), ("E4", 1), ("E4", 1), ("D4", 1), ("D4", 1), ("C4", 2)],
    "phrase_3": [("G4", 1), ("G4", 1), ("F4", 1), ("F4", 1), ("E4", 1), ("E4", 1), ("D4", 2)],
    "phrase_4": [("G4", 1), ("G4", 1), ("F4", 1), ("F4", 1), ("E4", 1), ("E4", 1), ("D4", 2)],
    "phrase_5": [("C4", 1), ("C4", 1), ("G4", 1), ("G4", 1), ("A4", 1), ("A4", 1), ("G4", 2)],
    "phrase_6": [("F4", 1), ("F4", 1), ("E4", 1), ("E4", 1), ("D4", 1), ("D4", 1), ("C4", 2)],
}


def midi_to_hz(midi: int) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def synth_note(note: str, beats: float, volume: float) -> list[int]:
    frequency = midi_to_hz(NOTE_MIDI[note])
    duration = beats * BEAT_SECONDS
    count = int(duration * SAMPLE_RATE)
    samples: list[int] = []
    attack = max(1, int(0.015 * SAMPLE_RATE))
    release = max(1, int(0.08 * SAMPLE_RATE))
    for i in range(count):
        envelope = 1.0
        if i < attack:
            envelope = i / attack
        elif i > count - release:
            envelope = max(0.0, (count - i) / release)
        # Bright but pitch-stable tone: fundamental plus a tiny harmonic.
        t = i / SAMPLE_RATE
        value = math.sin(2.0 * math.pi * frequency * t)
        value += 0.18 * math.sin(2.0 * math.pi * frequency * 2.0 * t)
        samples.append(int(max(-1.0, min(1.0, value * envelope * volume)) * 32767))
    gap = int(0.005 * SAMPLE_RATE)
    samples.extend([0] * gap)
    return samples


def render_phrase(phrase_id: str, volume: float) -> list[int]:
    if phrase_id not in PHRASES:
        raise ValueError(f"unknown phrase: {phrase_id}")
    samples: list[int] = []
    for note, beats in PHRASES[phrase_id]:
        samples.extend(synth_note(note, beats, volume))
    return samples


def write_wav(path: Path, samples: list[int]) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(struct.pack("<" + "h" * len(samples), *samples))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phrase", choices=sorted(PHRASES))
    parser.add_argument("--volume", type=float, default=0.24)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--no-play", action="store_true")
    args = parser.parse_args()

    out_path = args.out
    temp_dir = None
    if out_path is None:
        temp_dir = tempfile.TemporaryDirectory()
        out_path = Path(temp_dir.name) / f"{args.phrase}.wav"

    samples = render_phrase(args.phrase, args.volume)
    write_wav(out_path, samples)
    print(f"wrote {out_path} duration={len(samples) / SAMPLE_RATE:.2f}s samples={len(samples)}")

    if not args.no_play:
        player = shutil.which("afplay")
        if player is None:
            raise RuntimeError("afplay not found; pass --no-play and play the wav manually")
        subprocess.run([player, str(out_path)], check=True)

    if temp_dir is not None:
        temp_dir.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
