#!/usr/bin/env python3
"""Minimal BandToy recognition server.

This is intentionally narrow: it only recognizes Twinkle Twinkle Little Star.
The algorithm is a lightweight melody contour matcher, not a general Shazam.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import struct
import sys
import urllib.parse
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from statistics import median
from typing import Iterable

from emotion_ai import EmotionAi
from music_personality import CharacterMusicEngine, Emotion, build_personality_response
from pipeline_service import handle_pipeline_get, handle_pipeline_post


SAMPLE_RATE = 16000
TWINKLE_BPM = 96
BEAT_MS = 60000 / TWINKLE_BPM
BAR_MS = BEAT_MS * 4

TWINKLE_NOTES = [
    (60, 1), (60, 1), (67, 1), (67, 1), (69, 1), (69, 1), (67, 2),
    (65, 1), (65, 1), (64, 1), (64, 1), (62, 1), (62, 1), (60, 2),
    (67, 1), (67, 1), (65, 1), (65, 1), (64, 1), (64, 1), (62, 2),
    (67, 1), (67, 1), (65, 1), (65, 1), (64, 1), (64, 1), (62, 2),
    (60, 1), (60, 1), (67, 1), (67, 1), (69, 1), (69, 1), (67, 2),
    (65, 1), (65, 1), (64, 1), (64, 1), (62, 1), (62, 1), (60, 2),
]

TWINKLE_PHRASE_SEQUENCE = [
    {
        "phrase_id": "phrase_1",
        "label": "opening_call",
        "notes": [(60, 1), (60, 1), (67, 1), (67, 1), (69, 1), (69, 1), (67, 2)],
    },
    {
        "phrase_id": "phrase_2",
        "label": "opening_response",
        "notes": [(65, 1), (65, 1), (64, 1), (64, 1), (62, 1), (62, 1), (60, 2)],
    },
    {
        "phrase_id": "phrase_3",
        "label": "middle_call",
        "notes": [(67, 1), (67, 1), (65, 1), (65, 1), (64, 1), (64, 1), (62, 2)],
    },
    {
        "phrase_id": "phrase_4",
        "label": "middle_response",
        "notes": [(67, 1), (67, 1), (65, 1), (65, 1), (64, 1), (64, 1), (62, 2)],
    },
    {
        "phrase_id": "phrase_5",
        "label": "closing_call",
        "notes": [(60, 1), (60, 1), (67, 1), (67, 1), (69, 1), (69, 1), (67, 2)],
    },
    {
        "phrase_id": "phrase_6",
        "label": "closing_response",
        "notes": [(65, 1), (65, 1), (64, 1), (64, 1), (62, 1), (62, 1), (60, 2)],
    },
]

PHRASES = {phrase["phrase_id"]: phrase["notes"] for phrase in TWINKLE_PHRASE_SEQUENCE}
PHRASE_LABELS = {phrase["phrase_id"]: phrase["label"] for phrase in TWINKLE_PHRASE_SEQUENCE}
PHRASE_ORDER = [phrase["phrase_id"] for phrase in TWINKLE_PHRASE_SEQUENCE]
NEXT_PHRASE = {
    phrase_id: PHRASE_ORDER[(index + 1) % len(PHRASE_ORDER)]
    for index, phrase_id in enumerate(PHRASE_ORDER)
}
PHRASE_START_BEATS = {
    phrase_id: sum(sum(beats for _, beats in PHRASES[previous]) for previous in PHRASE_ORDER[:index])
    for index, phrase_id in enumerate(PHRASE_ORDER)
}
PHRASE_SIGNATURES = {
    phrase_id: tuple(midi for midi, _ in notes)
    for phrase_id, notes in PHRASES.items()
}
SESSION_EXPECTED_HEARD: dict[str, str] = {}

MIDI_NOTE_NAMES = {
    60: "C4",
    62: "D4",
    64: "E4",
    65: "F4",
    67: "G4",
    69: "A4",
}


def note_events(notes: list[tuple[int, int]], velocity: int = 88) -> list[dict]:
    events = []
    cursor_ms = 0
    for midi, beats in notes:
        duration_ms = int(BEAT_MS * beats)
        events.append({
            "note": MIDI_NOTE_NAMES[midi],
            "start_ms": cursor_ms,
            "duration_ms": duration_ms,
            "velocity": velocity,
        })
        cursor_ms += duration_ms
    return events


def phrase_duration_ms(notes: list[tuple[int, int]]) -> int:
    return int(sum(beats for _, beats in notes) * BEAT_MS)


def apply_session_context(result: dict, client_key: str) -> dict:
    if not result.get("recognized"):
        return result

    expected_phrase_id = SESSION_EXPECTED_HEARD.get(client_key)
    heard_phrase_id = result.get("heard_phrase_id", "")
    phrase_scores = result.get("phrase_scores", {})
    best_score = result.get("confidence", 0.0)

    if expected_phrase_id in PHRASES and heard_phrase_id in PHRASES:
        expected_score = phrase_scores.get(expected_phrase_id, {}).get("score", 0.0)
        same_melody = PHRASE_SIGNATURES[expected_phrase_id] == PHRASE_SIGNATURES[heard_phrase_id]
        if same_melody or expected_score >= best_score - 0.08:
            result["heard_phrase_id"] = expected_phrase_id
            result["heard_phrase_label"] = PHRASE_LABELS.get(expected_phrase_id, "")
            result["session_expected_match"] = True

    return result


def attach_response(result: dict, client_key: str) -> dict:
    if not result.get("recognized"):
        return result
    heard_phrase_id = result.get("heard_phrase_id", "")
    response_phrase_id = NEXT_PHRASE.get(heard_phrase_id)
    if response_phrase_id is None or response_phrase_id not in PHRASES:
        result["recognized"] = False
        return result
    response_notes = PHRASES[response_phrase_id]
    result["response_phrase_id"] = response_phrase_id
    result["response_phrase_label"] = PHRASE_LABELS.get(response_phrase_id, "")
    result["response_delay_ms"] = 500
    result["response_phrase"] = {
        "phrase_id": response_phrase_id,
        "instrument": "music_box",
        "duration_ms": phrase_duration_ms(response_notes),
        "notes": note_events(response_notes),
    }
    SESSION_EXPECTED_HEARD[client_key] = NEXT_PHRASE.get(response_phrase_id, PHRASE_ORDER[0])
    return result


def client_response(result: dict) -> dict:
    response = {
        "recognized": result.get("recognized", False),
        "song_id": result.get("song_id", 0),
        "confidence": result.get("confidence", 0.0),
    }
    if result.get("recognized"):
        response["position_ms"] = result.get("position_ms", 0)
        response["position_at_record_end_ms"] = result.get("position_at_record_end_ms", 0)
        response["join_after_ms"] = result.get("join_after_ms", 0)
        response["heard_phrase_id"] = result.get("heard_phrase_id", "")
        response["heard_phrase_label"] = result.get("heard_phrase_label", "")
        response["response_phrase_id"] = result.get("response_phrase_id", "")
        response["response_phrase_label"] = result.get("response_phrase_label", "")
        response["response_delay_ms"] = result.get("response_delay_ms", 500)
        response["response_phrase"] = result.get("response_phrase", {})
    return response


def maybe_accept_phrase_1_for_poc(result: dict) -> dict:
    return result


def personality_score_response() -> dict:
    engine = CharacterMusicEngine.musicbox_fox()
    return {
        "character_id": engine.theme.character_id,
        "instrument": engine.theme.instrument,
        "base_motif": [note.to_dict() for note in engine.theme.base_motif],
        "emotions": [emotion.value for emotion in Emotion],
    }


def personality_response_from_text(text: str) -> dict:
    result = EmotionAi().classify_text(text)
    response = build_personality_response(
        result.emotion,
        source_text=result.text or text,
        confidence=1.0 if not result.error else 0.6,
    )
    response["debug"]["ai_source"] = result.source
    response["debug"]["intent"] = result.intent
    response["debug"]["energy"] = result.energy
    if result.error:
        response["debug"]["ai_error"] = result.error
    return response


def personality_response_from_audio(body: bytes, content_type: str) -> dict:
    result = EmotionAi().classify_audio(body, content_type)
    if result.source == "asr_error":
        return {
            "recognized": False,
            "song_id": 1,
            "confidence": 0.0,
            "debug": {
                "ai_source": result.source,
                "ai_error": result.error,
                "ai_raw": result.raw,
            },
        }
    response = build_personality_response(
        result.emotion,
        source_text=result.text,
        confidence=1.0 if not result.error else 0.6,
    )
    response["debug"]["ai_source"] = result.source
    response["debug"]["intent"] = result.intent
    response["debug"]["energy"] = result.energy
    if result.error:
        response["debug"]["ai_error"] = result.error
    return response


def read_json_body(handler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def debug_text_header(handler) -> str:
    value = handler.headers.get("X-BandToy-Text", "")
    if value:
        return value
    encoded = handler.headers.get("X-BandToy-Text-Base64", "")
    if encoded:
        return base64.b64decode(encoded.encode("ascii")).decode("utf-8")
    return ""


def recognize_mode(path: str) -> str:
    parsed = urllib.parse.urlsplit(path)
    query = urllib.parse.parse_qs(parsed.query)
    requested = (query.get("mode", [""])[0] or "").strip().lower()
    return requested or os.environ.get("BANDTOY_RECOGNIZE_MODE", "twinkle").strip().lower()


def parse_audio(body: bytes, content_type: str) -> tuple[list[float], int]:
    if body[:4] == b"RIFF" or "wav" in content_type:
        with wave.open(BytesIO(body), "rb") as wav:
            rate = wav.getframerate()
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            frames = wav.readframes(wav.getnframes())
        if width != 2:
            raise ValueError("only 16-bit WAV is supported")
        raw = struct.unpack("<" + "h" * (len(frames) // 2), frames)
        if channels > 1:
            samples = [raw[i] / 32768.0 for i in range(0, len(raw), channels)]
        else:
            samples = [v / 32768.0 for v in raw]
        return samples, rate

    rate = SAMPLE_RATE
    if "x-sample-rate=" in content_type:
        marker = "x-sample-rate="
        start = content_type.index(marker) + len(marker)
        end = content_type.find(";", start)
        rate = int(content_type[start:] if end < 0 else content_type[start:end])
    raw = struct.unpack("<" + "h" * (len(body) // 2), body[: len(body) - (len(body) % 2)])
    return [v / 32768.0 for v in raw], rate


def resample_linear(samples: list[float], src_rate: int, dst_rate: int = SAMPLE_RATE) -> list[float]:
    if src_rate == dst_rate or not samples:
        return samples
    out_len = int(len(samples) * dst_rate / src_rate)
    out = []
    for i in range(out_len):
        pos = i * src_rate / dst_rate
        j = int(pos)
        frac = pos - j
        a = samples[min(j, len(samples) - 1)]
        b = samples[min(j + 1, len(samples) - 1)]
        out.append(a * (1 - frac) + b * frac)
    return out


def rms(frame: Iterable[float]) -> float:
    values = list(frame)
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))


def trim_silence(samples: list[float], rate: int = SAMPLE_RATE) -> tuple[list[float], dict]:
    if not samples:
        return samples, {"start_ms": 0, "end_ms": 0, "threshold": 0.0}

    frame = max(1, int(rate * 0.05))
    frame_rms = []
    for start in range(0, len(samples), frame):
        frame_rms.append(rms(samples[start:start + frame]))
    peak_rms = max(frame_rms) if frame_rms else 0.0
    sorted_rms = sorted(frame_rms)
    median_rms = sorted_rms[len(sorted_rms) // 2] if sorted_rms else 0.0
    high_rms = sorted_rms[int(len(sorted_rms) * 0.85)] if sorted_rms else 0.0
    # A button tap or I2S startup pop can be much louder than the melody.
    # Cap the gate so one transient cannot trim the whole phrase away.
    threshold = max(0.006, min(0.035, max(median_rms * 2.8, high_rms * 0.45, peak_rms * 0.08)))
    active = [index for index, value in enumerate(frame_rms) if value >= threshold]
    if not active:
        return samples, {
            "start_ms": 0,
            "end_ms": int(len(samples) * 1000 / rate),
            "threshold": round(threshold, 5),
            "median_frame_rms": round(median_rms, 5),
            "high_frame_rms": round(high_rms, 5),
        }

    pad_frames = 3
    first = max(0, active[0] - pad_frames)
    last = min(len(frame_rms) - 1, active[-1] + pad_frames)
    start_sample = first * frame
    end_sample = min(len(samples), (last + 1) * frame)
    return samples[start_sample:end_sample], {
        "start_ms": int(start_sample * 1000 / rate),
        "end_ms": int(end_sample * 1000 / rate),
        "threshold": round(threshold, 5),
        "peak_frame_rms": round(peak_rms, 5),
        "median_frame_rms": round(median_rms, 5),
        "high_frame_rms": round(high_rms, 5),
    }


def estimate_pitch(frame: list[float], rate: int = SAMPLE_RATE) -> float | None:
    energy = rms(frame)
    if energy < 0.003:
        return None
    min_freq, max_freq = 120, 760
    min_lag = int(rate / max_freq)
    max_lag = int(rate / min_freq)
    best_lag = 0
    best_corr = 0.0
    for lag in range(min_lag, max_lag + 1):
        corr = 0.0
        norm_a = 0.0
        norm_b = 0.0
        for i in range(0, len(frame) - lag, 2):
            a = frame[i]
            b = frame[i + lag]
            corr += a * b
            norm_a += a * a
            norm_b += b * b
        if norm_a <= 0 or norm_b <= 0:
            continue
        corr /= math.sqrt(norm_a * norm_b)
        if corr > best_corr:
            best_corr = corr
            best_lag = lag
    if best_corr < 0.25 or best_lag <= 0:
        return None
    return rate / best_lag


def hz_to_midi(freq: float) -> float:
    return 69 + 12 * math.log2(freq / 440.0)


def extract_melody(samples: list[float]) -> list[int | None]:
    frame = int(SAMPLE_RATE * 0.064)
    hop = int(SAMPLE_RATE * 0.125)
    notes: list[int | None] = []
    for start in range(0, max(0, len(samples) - frame), hop):
        segment = samples[start : start + frame]
        pitch = estimate_pitch(segment)
        if pitch is None:
            notes.append(None)
        else:
            notes.append(round(hz_to_midi(pitch)))
    return notes


def build_reference() -> list[int]:
    reference = []
    frames_per_beat = max(1, round(BEAT_MS / 125))
    for midi, beats in TWINKLE_NOTES:
        reference.extend([midi] * (frames_per_beat * beats))
    return reference


REFERENCE = build_reference()


def expand_phrase(notes: list[tuple[int, int]]) -> list[int]:
    reference = []
    frames_per_beat = max(1, round(BEAT_MS / 125))
    for midi, beats in notes:
        reference.extend([midi] * (frames_per_beat * beats))
    return reference


PHRASE_REFERENCES = {phrase_id: expand_phrase(notes) for phrase_id, notes in PHRASES.items()}


def resample_sequence(values: list[int], length: int) -> list[int]:
    if length <= 0 or not values:
        return []
    if length == 1:
        return [values[0]]
    return [values[round(i * (len(values) - 1) / (length - 1))] for i in range(length)]


def compact_notes(notes: list[int]) -> list[int]:
    compact = []
    for note in notes:
        if not compact or abs(note - compact[-1]) >= 2:
            compact.append(note)
    return compact


PHRASE_COMPACT = {phrase_id: compact_notes([midi for midi, _ in notes]) for phrase_id, notes in PHRASES.items()}


def significant_intervals(notes: list[int]) -> list[int]:
    intervals = []
    for previous, current in zip(notes, notes[1:]):
        delta = current - previous
        if abs(delta) >= 1:
            intervals.append(delta)
    return intervals


def drop_octave_duplicates(notes: list[int]) -> list[int]:
    compact = []
    for note in notes:
        if compact and note % 12 == compact[-1] % 12 and abs(note - compact[-1]) >= 11:
            continue
        compact.append(note)
    return compact


def normalize_octave_glitches(notes: list[int]) -> list[int]:
    if not notes:
        return []
    normalized = [notes[0]]
    for note in notes[1:]:
        candidates = [note + shift for shift in (-24, -12, 0, 12, 24)]
        best = min(candidates, key=lambda candidate: abs(candidate - normalized[-1]))
        normalized.append(best)
    return normalized


def contour_score(observed: list[int], reference: list[int]) -> float:
    observed_compact = compact_notes(observed)
    reference_compact = compact_notes(reference)
    count = min(len(observed_compact) - 1, len(reference_compact) - 1)
    if count <= 0:
        return 0.0
    total = 0.0
    for i in range(count):
        obs_delta = observed_compact[i + 1] - observed_compact[i]
        ref_delta = reference_compact[i + 1] - reference_compact[i]
        total += max(0.0, 1.0 - abs(obs_delta - ref_delta) / 5.0)
    return total / count


def interval_score(observed_compact: list[int], reference_compact: list[int]) -> float:
    observed_intervals = significant_intervals(observed_compact)
    reference_intervals = significant_intervals(reference_compact)
    count = min(len(observed_intervals), len(reference_intervals))
    if count <= 0:
        return 0.0
    total = 0.0
    for observed_delta, reference_delta in zip(observed_intervals[:count], reference_intervals[:count]):
        sign_bonus = 0.35 if (observed_delta > 0) == (reference_delta > 0) else 0.0
        size_score = max(0.0, 1.0 - abs(abs(observed_delta) - abs(reference_delta)) / 5.0)
        total += sign_bonus + 0.65 * size_score
    return total / count


def transposed_pitch_score(observed: list[int], reference: list[int]) -> tuple[float, int]:
    target = resample_sequence(reference, len(observed))
    if not target:
        return 0.0, 0
    transpose = round(median(obs - ref for obs, ref in zip(observed, target)))
    total = 0.0
    for obs, ref in zip(observed, target):
        diff = abs(obs - (ref + transpose))
        total += max(0.0, 1.0 - diff / 5.0)
    return total / len(observed), transpose


def score_phrase(observed_notes: list[int], reference: list[int]) -> tuple[float, int]:
    target = resample_sequence(reference, len(observed_notes))
    if not target:
        return 0.0, 0
    pitch_score, transpose = transposed_pitch_score(observed_notes, reference)
    return round(0.72 * pitch_score + 0.28 * contour_score(observed_notes, target), 3), transpose


def next_bar_delay(position_ms: int) -> int:
    if position_ms <= 0:
        return int(BAR_MS)
    delay = int(BAR_MS - (position_ms % int(BAR_MS)))
    if delay < 250:
        delay += int(BAR_MS)
    return delay


def match_position(observed: list[int | None], audio_duration_ms: int) -> dict:
    pitched = [(index, note) for index, note in enumerate(observed) if note is not None]
    if len(pitched) < 4:
        return {
            "song_id": 1,
            "title": "Twinkle Twinkle Little Star",
            "confidence": 0.0,
            "position_ms": 0,
            "position_at_record_end_ms": 0,
            "bar_index": 0,
            "beat_in_bar": 0.0,
            "join_after_ms": int(BAR_MS),
            "recognized": False,
        }
    first_pitch_frame = pitched[0][0]
    first_pitch_ms = first_pitch_frame * 125
    observed_notes = normalize_octave_glitches([note for _, note in pitched])
    observed_compact = compact_notes(observed_notes)
    observed_melodic = drop_octave_duplicates(observed_compact)
    observed_intervals = significant_intervals(observed_melodic)
    first_large_interval = next((delta for delta in observed_intervals if abs(delta) >= 4), 0)
    upward_fifth_interval = next((delta for delta in observed_intervals if 5 <= delta <= 9), 0)

    phrase_scores = {}
    best_phrase_id = ""
    best_score = -1.0
    best_transpose = 0
    for phrase_id, reference in PHRASE_REFERENCES.items():
        frame_score, transpose = score_phrase(observed_notes, reference)
        shape_score = interval_score(observed_compact, PHRASE_COMPACT[phrase_id])
        score = round(0.58 * frame_score + 0.42 * shape_score, 3)
        phrase_scores[phrase_id] = {
            "score": score,
            "frame_score": frame_score,
            "shape_score": round(shape_score, 3),
            "transpose": transpose,
        }
        if score > best_score:
            best_score = score
            best_phrase_id = phrase_id
            best_transpose = transpose

    if upward_fifth_interval:
        best_phrase_id = "phrase_1"
        best_score = max(best_score, 0.76)
        best_transpose = phrase_scores["phrase_1"]["transpose"]
        phrase_scores["phrase_1"]["score"] = round(best_score, 3)
    elif first_large_interval >= 4 and phrase_scores["phrase_1"]["score"] >= 0.34:
        best_phrase_id = "phrase_1"
        best_score = max(best_score, 0.74)
        best_transpose = phrase_scores["phrase_1"]["transpose"]
        phrase_scores["phrase_1"]["score"] = round(best_score, 3)

    sorted_scores = sorted((value["score"], phrase_id) for phrase_id, value in phrase_scores.items())
    second_score = sorted_scores[-2][0] if len(sorted_scores) >= 2 else 0.0
    score_margin = best_score - second_score

    position_ms = int(PHRASE_START_BEATS.get(best_phrase_id, 0) * BEAT_MS)
    position_at_record_end_ms = position_ms + max(0, audio_duration_ms - first_pitch_ms)
    beat_position = position_at_record_end_ms / BEAT_MS
    bar_index = int(beat_position // 4)
    beat_in_bar = beat_position % 4

    return {
        "song_id": 1,
        "title": "Twinkle Twinkle Little Star",
        "confidence": round(float(best_score), 3),
        "position_ms": position_ms,
        "position_at_record_end_ms": int(position_at_record_end_ms),
        "bar_index": bar_index,
        "beat_in_bar": round(float(beat_in_bar), 2),
        "join_after_ms": next_bar_delay(position_at_record_end_ms),
        "recognized": (
            best_score >= 0.54
            or (best_score >= 0.44 and score_margin >= 0.08)
            or (best_phrase_id == "phrase_1" and best_score >= 0.34)
        ),
        "heard_phrase_id": best_phrase_id,
        "heard_phrase_label": PHRASE_LABELS.get(best_phrase_id, ""),
        "phrase_scores": phrase_scores,
        "score_margin": round(float(score_margin), 3),
        "transpose": best_transpose,
        "observed_compact": observed_compact[:12],
        "observed_melodic": observed_melodic[:12],
        "observed_intervals": observed_intervals[:12],
        "first_large_interval": first_large_interval,
        "upward_fifth_interval": upward_fifth_interval,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if handle_pipeline_get(self, self.path):
            return
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path == "/health":
            self.send_json({"ok": True})
            return
        if path == "/reset_session":
            SESSION_EXPECTED_HEARD.pop(self.client_address[0], None)
            self.send_json({"ok": True, "reset_client": self.client_address[0]})
            return
        if path == "/reset_sessions":
            SESSION_EXPECTED_HEARD.clear()
            self.send_json({"ok": True, "reset_all": True})
            return
        if path == "/personality/score":
            self.send_json(personality_score_response())
            return
        if path == "/score":
            self.send_json({
                "song_id": 1,
                "title": "Twinkle Twinkle Little Star",
                "bpm": TWINKLE_BPM,
                "phrases": [
                    {
                        "phrase_id": phrase_id,
                        "label": PHRASE_LABELS[phrase_id],
                        "next_phrase_id": NEXT_PHRASE[phrase_id],
                        "start_ms": int(PHRASE_START_BEATS[phrase_id] * BEAT_MS),
                        "duration_ms": phrase_duration_ms(PHRASES[phrase_id]),
                    }
                    for phrase_id in PHRASE_ORDER
                ],
            })
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if handle_pipeline_post(self, self.path):
            return
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path == "/emotion":
            try:
                request = read_json_body(self)
                text = str(request.get("text", ""))
                self.send_json(personality_response_from_text(text))
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        if path != "/recognize":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            content_type = self.headers.get("Content-Type", "")
            body = self.rfile.read(length)
            if recognize_mode(self.path) == "personality":
                debug_text = debug_text_header(self)
                result = personality_response_from_text(debug_text) if debug_text else personality_response_from_audio(body, content_type)
                self.send_json(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                return
            samples, rate = parse_audio(body, content_type)
            samples = resample_linear(samples, rate)
            raw_duration_ms = int(len(samples) * 1000 / SAMPLE_RATE)
            raw_rms = rms(samples)
            samples, trim_debug = trim_silence(samples)
            melody = extract_melody(samples)
            audio_duration_ms = int(len(samples) * 1000 / SAMPLE_RATE)
            result = match_position(melody, audio_duration_ms)
            pitched_indices = [index for index, note in enumerate(melody) if note is not None]
            result["debug"] = {
                "bytes": len(body),
                "samples": len(samples),
                "raw_duration_ms": raw_duration_ms,
                "duration_ms": audio_duration_ms,
                "raw_rms": round(raw_rms, 5),
                "rms": round(rms(samples), 5),
                "trim": trim_debug,
                "pitched_frames": sum(1 for note in melody if note is not None),
                "first_pitch_ms": (pitched_indices[0] * 125) if pitched_indices else None,
                "phrase_scores": result.get("phrase_scores", {}),
                "score_margin": result.get("score_margin", 0.0),
                "observed_compact": result.get("observed_compact", []),
                "observed_melodic": result.get("observed_melodic", []),
                "observed_intervals": result.get("observed_intervals", []),
                "first_large_interval": result.get("first_large_interval", 0),
                "upward_fifth_interval": result.get("upward_fifth_interval", 0),
                "transpose": result.get("transpose", 0),
            }
            client_key = self.client_address[0]
            result = apply_session_context(maybe_accept_phrase_1_for_poc(result), client_key)
            result = attach_response(result, client_key)
            if result.get("recognized"):
                result["debug"]["session_next_expected_heard"] = SESSION_EXPECTED_HEARD.get(client_key, "")
            self.send_json(client_response(result))
            print(json.dumps(result), flush=True)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def send_json(self, value: dict, status: int = 200) -> None:
        payload = json.dumps(value).encode("utf-8")
        self.send_json_bytes(payload, status)

    def send_json_bytes(self, payload: bytes, status: int = 200) -> None:
        self.send_bytes(payload, status, "application/json")

    def send_bytes(self, payload: bytes, status: int = 200, content_type: str = "application/octet-stream") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:  # type: ignore[override]
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = QuietThreadingHTTPServer((args.host, args.port), Handler)
    print(f"BandToy recognition server listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
