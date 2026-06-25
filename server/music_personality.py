from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Emotion(Enum):
    HAPPY = "happy"
    SAD = "sad"
    COMFORT = "comfort"
    SLEEP = "sleep"
    CURIOUS = "curious"
    GREETING = "greeting"
    THINKING = "thinking"


@dataclass(frozen=True)
class NoteEvent:
    note: str
    start_ms: int
    duration_ms: int
    velocity: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "note": self.note,
            "start_ms": self.start_ms,
            "duration_ms": self.duration_ms,
            "velocity": self.velocity,
        }


@dataclass(frozen=True)
class CharacterTheme:
    character_id: str
    instrument: str
    base_motif: list[NoteEvent]


@dataclass(frozen=True)
class MotifVariation:
    emotion: Emotion
    tempo_scale: float
    transpose_semitones: int
    velocity_scale: float
    override_notes: list[NoteEvent]


class EmotionRouter:
    def parse_input(self, value: str) -> Emotion:
        text = (value or "").strip().lower()
        if not text:
            return Emotion.THINKING
        keyword_map = {
            Emotion.HAPPY: ["happy", "开心", "高兴", "快乐", "兴奋", "太好了"],
            Emotion.SAD: ["sad", "难过", "伤心", "失落", "沮丧", "低落"],
            Emotion.COMFORT: ["comfort", "安慰", "累", "疲惫", "压力", "抱抱", "害怕"],
            Emotion.SLEEP: ["sleep", "困", "睡", "晚安", "休息"],
            Emotion.CURIOUS: ["curious", "好奇", "为什么", "吗", "?", "？"],
            Emotion.GREETING: ["hello", "hi", "你好", "早上好"],
            Emotion.THINKING: ["thinking", "想想", "不知道"],
        }
        for emotion, keywords in keyword_map.items():
            if any(keyword in text for keyword in keywords):
                return emotion
        return Emotion.CURIOUS


class CharacterMusicEngine:
    def __init__(self, theme: CharacterTheme, variations: dict[Emotion, MotifVariation]):
        self.theme = theme
        self._variations = variations

    @classmethod
    def musicbox_fox(cls) -> "CharacterMusicEngine":
        base = [
            NoteEvent("C5", 0, 280, 86),
            NoteEvent("E5", 320, 260, 84),
            NoteEvent("G5", 620, 360, 88),
            NoteEvent("E5", 1040, 420, 78),
        ]
        theme = CharacterTheme(
            character_id="musicbox_fox",
            instrument="music_box",
            base_motif=base,
        )
        variations = {
            Emotion.HAPPY: MotifVariation(Emotion.HAPPY, 0.82, 0, 1.08, [
                NoteEvent("C5", 0, 220, 92),
                NoteEvent("E5", 240, 210, 94),
                NoteEvent("G5", 470, 230, 96),
                NoteEvent("C6", 720, 300, 98),
                NoteEvent("G5", 1080, 360, 88),
            ]),
            Emotion.SAD: MotifVariation(Emotion.SAD, 1.35, 0, 0.70, [
                NoteEvent("C5", 0, 520, 66),
                NoteEvent("Eb5", 640, 520, 62),
                NoteEvent("G5", 1280, 620, 64),
                NoteEvent("Eb5", 2020, 560, 58),
                NoteEvent("C5", 2700, 840, 56),
            ]),
            Emotion.COMFORT: MotifVariation(Emotion.COMFORT, 1.25, 0, 0.76, [
                NoteEvent("C5", 0, 440, 72),
                NoteEvent("E5", 720, 520, 70),
                NoteEvent("G5", 1500, 700, 68),
                NoteEvent("E5", 2900, 880, 64),
            ]),
            Emotion.SLEEP: MotifVariation(Emotion.SLEEP, 1.75, -5, 0.48, [
                NoteEvent("C5", 0, 900, 48),
                NoteEvent("G4", 1600, 1100, 44),
                NoteEvent("C5", 3300, 1600, 42),
            ]),
            Emotion.CURIOUS: MotifVariation(Emotion.CURIOUS, 0.72, 0, 0.90, [
                NoteEvent("C5", 0, 190, 78),
                NoteEvent("E5", 230, 180, 82),
                NoteEvent("G5", 450, 190, 84),
                NoteEvent("A5", 760, 520, 78),
            ]),
            Emotion.GREETING: MotifVariation(Emotion.GREETING, 0.88, 0, 1.00, [
                NoteEvent("C5", 0, 240, 86),
                NoteEvent("E5", 300, 240, 86),
                NoteEvent("G5", 600, 280, 88),
                NoteEvent("E5", 980, 260, 80),
                NoteEvent("C5", 1320, 360, 78),
            ]),
            Emotion.THINKING: MotifVariation(Emotion.THINKING, 1.05, 0, 0.82, [
                NoteEvent("C5", 0, 280, 70),
                NoteEvent("E5", 430, 280, 70),
                NoteEvent("G5", 860, 360, 72),
                NoteEvent("A5", 1420, 480, 68),
            ]),
        }
        return cls(theme, variations)

    def generate_variation(self, emotion: Emotion) -> list[NoteEvent]:
        variation = self._variations.get(emotion) or self._variations[Emotion.CURIOUS]
        return [
            NoteEvent(
                note=note.note,
                start_ms=int(note.start_ms * variation.tempo_scale),
                duration_ms=max(80, int(note.duration_ms * variation.tempo_scale)),
                velocity=max(1, min(127, int(note.velocity * variation.velocity_scale))),
            )
            for note in variation.override_notes
        ]


def emotion_label(emotion: Emotion) -> str:
    labels = {
        Emotion.HAPPY: "Happy",
        Emotion.SAD: "Sad",
        Emotion.COMFORT: "Comfort",
        Emotion.SLEEP: "Sleep",
        Emotion.CURIOUS: "Curious",
        Emotion.GREETING: "Greeting",
        Emotion.THINKING: "Thinking",
    }
    return labels[emotion]


def build_personality_response(emotion: Emotion, source_text: str = "", confidence: float = 1.0) -> dict[str, Any]:
    engine = CharacterMusicEngine.musicbox_fox()
    notes = engine.generate_variation(emotion)
    duration_ms = max((note.start_ms + note.duration_ms for note in notes), default=0)
    phrase_id = f"variation_{emotion.value}"
    return {
        "recognized": True,
        "song_id": 1,
        "confidence": round(confidence, 3),
        "emotion": emotion.value,
        "emotion_label": emotion_label(emotion),
        "character_id": engine.theme.character_id,
        "instrument": engine.theme.instrument,
        "response_phrase_id": phrase_id,
        "response_phrase_label": emotion.value,
        "response_delay_ms": 250,
        "response_phrase": {
            "phrase_id": phrase_id,
            "instrument": engine.theme.instrument,
            "duration_ms": duration_ms,
            "notes": [note.to_dict() for note in notes],
        },
        "debug": {
            "source_text": source_text,
            "base_motif": [note.note for note in engine.theme.base_motif],
            "generated_notes": [note.to_dict() for note in notes],
        },
    }
