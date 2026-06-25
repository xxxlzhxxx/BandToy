#!/usr/bin/env python3
"""Generate and play deterministic BandToy song-chain test phrases."""

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
NOTE_MIDI = {
    "C4": 60,
    "C#5": 73,
    "B3": 59,
    "C#4": 61,
    "D#4": 63,
    "D#5": 75,
    "D4": 62,
    "E4": 64,
    "E5": 76,
    "F4": 65,
    "F#4": 66,
    "F#5": 78,
    "G4": 67,
    "G5": 79,
    "G#4": 68,
    "G#5": 80,
    "A4": 69,
    "A5": 81,
    "B4": 71,
    "B5": 83,
    "C5": 72,
    "C#6": 85,
}

PHRASES = {
    "phrase_1": {"bpm": 96, "notes": [("C4", 1), ("C4", 1), ("G4", 1), ("G4", 1), ("A4", 1), ("A4", 1), ("G4", 2)]},
    "phrase_2": {"bpm": 96, "notes": [("F4", 1), ("F4", 1), ("E4", 1), ("E4", 1), ("D4", 1), ("D4", 1), ("C4", 2)]},
    "phrase_3": {"bpm": 96, "notes": [("G4", 1), ("G4", 1), ("F4", 1), ("F4", 1), ("E4", 1), ("E4", 1), ("D4", 2)]},
    "phrase_4": {"bpm": 96, "notes": [("G4", 1), ("G4", 1), ("F4", 1), ("F4", 1), ("E4", 1), ("E4", 1), ("D4", 2)]},
    "phrase_5": {"bpm": 96, "notes": [("C4", 1), ("C4", 1), ("G4", 1), ("G4", 1), ("A4", 1), ("A4", 1), ("G4", 2)]},
    "phrase_6": {"bpm": 96, "notes": [("F4", 1), ("F4", 1), ("E4", 1), ("E4", 1), ("D4", 1), ("D4", 1), ("C4", 2)]},
    "salut_phrase_1": {"bpm": 80, "notes": [("G#4", 1), ("B3", 0.5), ("G#4", 0.5), ("F#4", 0.5), ("E4", 0.5), ("D#4", 0.5), ("E4", 0.5), ("A4", 1)]},
    "salut_phrase_2": {"bpm": 80, "notes": [("A4", 1), ("A4", 1), ("B3", 0.5), ("G#4", 1), ("C4", 0.5), ("G#4", 0.5), ("F#4", 0.5), ("E4", 0.5), ("D#4", 0.5), ("E4", 0.5), ("F#4", 1)]},
    "salut_phrase_3": {"bpm": 80, "notes": [("F#4", 1.5), ("G4", 0.5), ("G#4", 1), ("B3", 0.5), ("G#4", 0.5), ("F#4", 0.5), ("E4", 0.5), ("D#4", 0.5), ("E4", 0.5), ("C#5", 1)]},
    "salut_phrase_4": {"bpm": 80, "notes": [("C#5", 1), ("C#5", 1), ("B4", 0.5), ("A4", 0.5), ("G#4", 1), ("F#4", 0.5), ("E4", 0.5), ("C#4", 1), ("D#4", 1), ("E4", 2)]},
}


def midi_to_hz(midi: int) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def synth_note(note: str, beats: float, beat_seconds: float, volume: float) -> list[int]:
    frequency = midi_to_hz(NOTE_MIDI[note])
    duration = beats * beat_seconds
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
        # Pitch-stable tone. Keep this close to a sine wave so the simple
        # autocorrelation recognizer does not lock onto a harmonic.
        t = i / SAMPLE_RATE
        value = math.sin(2.0 * math.pi * frequency * t)
        samples.append(int(max(-1.0, min(1.0, value * envelope * volume)) * 32767))
    gap = int(0.005 * SAMPLE_RATE)
    samples.extend([0] * gap)
    return samples


def render_phrase(phrase_id: str, volume: float) -> list[int]:
    if phrase_id not in PHRASES:
        raise ValueError(f"unknown phrase: {phrase_id}")
    phrase = PHRASES[phrase_id]
    beat_seconds = 60.0 / phrase["bpm"]
    samples: list[int] = []
    for note, beats in phrase["notes"]:
        samples.extend(synth_note(note, beats, beat_seconds, volume))
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
