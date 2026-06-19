#!/usr/bin/env python3
"""Minimal BandToy recognition server.

This is intentionally narrow: it only recognizes Twinkle Twinkle Little Star.
The algorithm is a lightweight melody contour matcher, not a general Shazam.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from typing import Iterable


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

TWINKLE_RESPONSE_1_NOTES = [
    {"note": "F4", "start_ms": 0, "duration_ms": int(BEAT_MS), "velocity": 90},
    {"note": "F4", "start_ms": int(BEAT_MS), "duration_ms": int(BEAT_MS), "velocity": 90},
    {"note": "E4", "start_ms": int(BEAT_MS * 2), "duration_ms": int(BEAT_MS), "velocity": 88},
    {"note": "E4", "start_ms": int(BEAT_MS * 3), "duration_ms": int(BEAT_MS), "velocity": 88},
    {"note": "D4", "start_ms": int(BEAT_MS * 4), "duration_ms": int(BEAT_MS), "velocity": 84},
    {"note": "D4", "start_ms": int(BEAT_MS * 5), "duration_ms": int(BEAT_MS), "velocity": 84},
    {"note": "C4", "start_ms": int(BEAT_MS * 6), "duration_ms": int(BEAT_MS * 2), "velocity": 80},
]


def attach_response(result: dict) -> dict:
    if not result.get("recognized"):
        return result
    result["heard_phrase_id"] = "phrase_1"
    result["response_phrase_id"] = "response_1"
    result["response_delay_ms"] = 500
    result["response_phrase"] = {
        "phrase_id": "response_1",
        "instrument": "music_box",
        "duration_ms": int(BEAT_MS * 8),
        "notes": TWINKLE_RESPONSE_1_NOTES,
    }
    return result


def client_response(result: dict) -> dict:
    response = {
        "recognized": result.get("recognized", False),
        "song_id": result.get("song_id", 0),
        "confidence": result.get("confidence", 0.0),
    }
    if result.get("recognized"):
        response["heard_phrase_id"] = result.get("heard_phrase_id", "")
        response["response_phrase_id"] = result.get("response_phrase_id", "")
        response["response_delay_ms"] = result.get("response_delay_ms", 500)
        response["response_phrase"] = result.get("response_phrase", {})
    return response


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
    observed_notes = [note for _, note in pitched]

    best_score = -1.0
    best_offset = 0
    max_offset = max(1, len(REFERENCE) - len(observed_notes))
    for offset in range(max_offset):
        total = 0.0
        count = 0
        for i, note in enumerate(observed_notes):
            diff = abs(note - REFERENCE[offset + i])
            total += max(0.0, 1.0 - diff / 5.0)
            count += 1
        score = total / max(1, count)
        if score > best_score:
            best_score = score
            best_offset = offset

    frame_ms = 125
    position_ms = int(best_offset * frame_ms)
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
        "recognized": best_score >= 0.55,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json({"ok": True})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/recognize":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            content_type = self.headers.get("Content-Type", "")
            body = self.rfile.read(length)
            samples, rate = parse_audio(body, content_type)
            samples = resample_linear(samples, rate)
            melody = extract_melody(samples)
            audio_duration_ms = int(len(samples) * 1000 / SAMPLE_RATE)
            result = attach_response(match_position(melody, audio_duration_ms))
            pitched_indices = [index for index, note in enumerate(melody) if note is not None]
            result["debug"] = {
                "bytes": len(body),
                "samples": len(samples),
                "duration_ms": audio_duration_ms,
                "rms": round(rms(samples), 5),
                "pitched_frames": sum(1 for note in melody if note is not None),
                "first_pitch_ms": (pitched_indices[0] * 125) if pitched_indices else None,
            }
            self.send_json(client_response(result))
            print(json.dumps(result), flush=True)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def send_json(self, value: dict, status: int = 200) -> None:
        payload = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
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
