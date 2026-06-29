#!/usr/bin/env python3
"""Minimal BandToy recognition server.

The song-chain path recognizes a tiny built-in phrase library and returns the
next phrase for call-and-response playback. The algorithm is a lightweight
melody contour matcher, not a general Shazam.
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

SALUT_DAMOUR_BPM = 80
SALUT_DAMOUR_PHRASE_SEQUENCE = [
    {
        "phrase_id": "salut_phrase_1",
        "label": "opening_sigh",
        "notes": [(68, 1), (59, 0.5), (68, 0.5), (66, 0.5), (64, 0.5), (63, 0.5), (64, 0.5), (69, 1)],
    },
    {
        "phrase_id": "salut_phrase_2",
        "label": "opening_answer",
        "notes": [(69, 1), (69, 1), (59, 0.5), (68, 1), (60, 0.5), (68, 0.5), (66, 0.5), (64, 0.5), (63, 0.5), (64, 0.5), (66, 1)],
    },
    {
        "phrase_id": "salut_phrase_3",
        "label": "lifted_call",
        "notes": [(66, 1.5), (67, 0.5), (68, 1), (59, 0.5), (68, 0.5), (66, 0.5), (64, 0.5), (63, 0.5), (64, 0.5), (73, 1)],
    },
    {
        "phrase_id": "salut_phrase_4",
        "label": "cadence_answer",
        "notes": [(73, 1), (73, 1), (71, 0.5), (69, 0.5), (68, 1), (66, 0.5), (64, 0.5), (61, 1), (63, 1), (64, 2)],
    },
]

SONG_DEFINITIONS = [
    {
        "song_id": 1,
        "title": "Twinkle Twinkle Little Star",
        "bpm": TWINKLE_BPM,
        "phrases": TWINKLE_PHRASE_SEQUENCE,
    },
    {
        "song_id": 2,
        "title": "Salut d'Amour",
        "bpm": SALUT_DAMOUR_BPM,
        "phrases": SALUT_DAMOUR_PHRASE_SEQUENCE,
    },
]

PHRASES = {}
PHRASE_LABELS = {}
PHRASE_ORDER = []
PHRASE_START_BEATS = {}
PHRASE_SIGNATURES = {}
PHRASE_SONG_ID = {}
PHRASE_TITLE = {}
PHRASE_BPM = {}
PHRASE_BEAT_MS = {}
NEXT_PHRASE = {}

for song in SONG_DEFINITIONS:
    phrases = song["phrases"]
    order = [phrase["phrase_id"] for phrase in phrases]
    for index, phrase in enumerate(phrases):
        phrase_id = phrase["phrase_id"]
        notes = phrase["notes"]
        PHRASES[phrase_id] = notes
        PHRASE_LABELS[phrase_id] = phrase["label"]
        PHRASE_ORDER.append(phrase_id)
        PHRASE_START_BEATS[phrase_id] = sum(
            sum(beats for _, beats in previous["notes"])
            for previous in phrases[:index]
        )
        PHRASE_SIGNATURES[phrase_id] = tuple(midi for midi, _ in notes)
        PHRASE_SONG_ID[phrase_id] = song["song_id"]
        PHRASE_TITLE[phrase_id] = song["title"]
        PHRASE_BPM[phrase_id] = song["bpm"]
        PHRASE_BEAT_MS[phrase_id] = 60000 / song["bpm"]
        NEXT_PHRASE[phrase_id] = order[(index + 1) % len(order)]

SESSION_EXPECTED_HEARD: dict[str, str] = {}

MIDI_NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]


def midi_note_name(midi: int) -> str:
    return f"{MIDI_NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def note_events(notes: list[tuple[int, float]], beat_ms: float, velocity: int = 88) -> list[dict]:
    events = []
    cursor_ms = 0
    for midi, beats in notes:
        duration_ms = int(beat_ms * beats)
        events.append({
            "note": midi_note_name(midi),
            "start_ms": cursor_ms,
            "duration_ms": duration_ms,
            "velocity": velocity,
        })
        cursor_ms += duration_ms
    return events


def phrase_duration_ms(notes: list[tuple[int, float]], beat_ms: float) -> int:
    return int(sum(beats for _, beats in notes) * beat_ms)


def apply_session_context(result: dict, client_key: str) -> dict:
    if not result.get("recognized"):
        return result

    expected_phrase_id = SESSION_EXPECTED_HEARD.get(client_key)
    heard_phrase_id = result.get("heard_phrase_id", "")
    phrase_scores = result.get("phrase_scores", {})
    best_score = result.get("confidence", 0.0)

    if expected_phrase_id in PHRASES and heard_phrase_id in PHRASES:
        if PHRASE_SONG_ID.get(expected_phrase_id) != PHRASE_SONG_ID.get(heard_phrase_id):
            return result
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
    beat_ms = PHRASE_BEAT_MS[response_phrase_id]
    result["response_phrase_id"] = response_phrase_id
    result["response_phrase_label"] = PHRASE_LABELS.get(response_phrase_id, "")
    result["response_delay_ms"] = 500
    result["response_phrase"] = {
        "phrase_id": response_phrase_id,
        "instrument": "music_box",
        "duration_ms": phrase_duration_ms(response_notes, beat_ms),
        "notes": note_events(response_notes, beat_ms),
    }
    SESSION_EXPECTED_HEARD[client_key] = NEXT_PHRASE.get(response_phrase_id, response_phrase_id)
    return result


def client_response(result: dict) -> dict:
    response = {
        "recognized": result.get("recognized", False),
        "song_id": result.get("song_id", 0),
        "confidence": result.get("confidence", 0.0),
    }
    if result.get("recognized"):
        response["title"] = result.get("title", "")
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


def song_definition_for_phrase(phrase_id: str) -> dict | None:
    song_id = PHRASE_SONG_ID.get(phrase_id)
    for song in SONG_DEFINITIONS:
        if song["song_id"] == song_id:
            return song
    return None


def song_melody_notes(song: dict) -> list[tuple[int, float]]:
    notes = []
    for phrase in song["phrases"]:
        notes.extend(phrase["notes"])
    return notes


def phrase_note_range(phrase_id: str) -> tuple[int, int]:
    song = song_definition_for_phrase(phrase_id)
    if song is None:
        return 0, 0
    cursor = 0
    for phrase in song["phrases"]:
        start = cursor
        cursor += len(phrase["notes"])
        if phrase["phrase_id"] == phrase_id:
            return start, cursor
    return 0, 0


def score_note_events(notes: list[tuple[int, float]]) -> list[dict]:
    return [
        {"midi": midi, "note": midi_note_name(midi), "beats": beats}
        for midi, beats in notes
    ]


def phrase_summary(phrase_id: str) -> dict:
    notes = PHRASES[phrase_id]
    beat_ms = PHRASE_BEAT_MS[phrase_id]
    start_note_index, end_note_index = phrase_note_range(phrase_id)
    return {
        "phrase_id": phrase_id,
        "label": PHRASE_LABELS[phrase_id],
        "song_id": PHRASE_SONG_ID[phrase_id],
        "title": PHRASE_TITLE[phrase_id],
        "bpm": PHRASE_BPM[phrase_id],
        "next_phrase_id": NEXT_PHRASE[phrase_id],
        "start_note_index": start_note_index,
        "end_note_index": end_note_index,
        "duration_ms": phrase_duration_ms(notes, beat_ms),
        "note_count": len(notes),
        "notes": note_events(notes, beat_ms),
        "score_notes": score_note_events(notes),
        "melody_slice": score_note_events(notes),
    }


def library_songs_response() -> dict:
    songs = []
    for song in SONG_DEFINITIONS:
        phrases = [phrase_summary(phrase["phrase_id"]) for phrase in song["phrases"]]
        melody_notes = score_note_events(song_melody_notes(song))
        songs.append({
            "song_id": song["song_id"],
            "title": song["title"],
            "bpm": song["bpm"],
            "melody_note_count": len(melody_notes),
            "melody_notes": melody_notes,
            "phrase_count": len(phrases),
            "phrases": phrases,
        })
    return {"songs": songs}


def library_phrase_response(phrase_id: str) -> dict | None:
    if phrase_id not in PHRASES:
        return None
    response = phrase_summary(phrase_id)
    next_phrase_id = NEXT_PHRASE[phrase_id]
    response["response_phrase"] = phrase_summary(next_phrase_id)
    return response


def library_page_html() -> str:
    return r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BandToy Library</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #1c1b18;
      --muted: #6f6a61;
      --line: #d8d1c4;
      --paper: #fbfaf7;
      --panel: #ffffff;
      --accent: #2f6f73;
      --accent-soft: #e3f0ef;
      --warn: #8b5e1d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font: 14px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--paper);
      color: var(--ink);
    }
    header {
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 20px;
      border-bottom: 1px solid var(--line);
      background: #f5f1ea;
    }
    h1 { margin: 0; font-size: 18px; font-weight: 700; letter-spacing: 0; }
    .status { color: var(--muted); font-size: 13px; }
    main {
      display: grid;
      grid-template-columns: 260px minmax(360px, 1fr) minmax(420px, 1.1fr);
      min-height: calc(100vh - 56px);
    }
    aside, section {
      min-width: 0;
      border-right: 1px solid var(--line);
      background: var(--panel);
    }
    section:last-child { border-right: 0; }
    .pane-title {
      height: 44px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 14px;
      border-bottom: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
    }
    .list { padding: 10px; display: grid; gap: 8px; }
    button {
      appearance: none;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 6px;
      padding: 9px 10px;
      text-align: left;
      cursor: pointer;
      font: inherit;
    }
    button:hover, button.active { border-color: var(--accent); background: var(--accent-soft); }
    .song-title, .phrase-id { font-weight: 650; }
    .meta { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .phrase-list { padding: 10px; display: grid; gap: 8px; }
    .melody-timeline {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      background: #fbfaf7;
    }
    .note-cell {
      min-width: 54px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 6px;
      background: #fff;
      text-align: center;
    }
    .note-cell.in-phrase { border-color: var(--accent); background: var(--accent-soft); }
    .note-cell .idx { color: var(--muted); font-size: 11px; }
    .note-cell .note { display: block; font-weight: 700; }
    .detail { padding: 14px; overflow: auto; }
    .detail h2 { margin: 0 0 4px; font-size: 19px; letter-spacing: 0; }
    .detail h3 { margin: 18px 0 8px; font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin: 12px 0;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      background: #fff;
    }
    .metric b { display: block; font-size: 16px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
    .actions button { text-align: center; }
    table { width: 100%; border-collapse: collapse; background: #fff; }
    th, td { border-bottom: 1px solid var(--line); padding: 7px 8px; text-align: left; white-space: nowrap; }
    th { color: var(--muted); font-weight: 600; font-size: 12px; }
    code {
      display: block;
      white-space: pre-wrap;
      background: #f5f1ea;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      color: var(--warn);
    }
    @media (max-width: 980px) {
      main { grid-template-columns: 1fr; }
      aside, section { border-right: 0; border-bottom: 1px solid var(--line); }
    }
  </style>
</head>
<body>
  <header>
    <h1>BandToy Library</h1>
    <div class="status" id="status">loading /library/songs</div>
  </header>
  <main>
    <aside>
      <div class="pane-title">Songs</div>
      <div class="list" id="song-list"></div>
    </aside>
    <section>
      <div class="pane-title">Melody & Phrases</div>
      <div class="melody-timeline" id="melody-timeline"></div>
      <div class="phrase-list" id="phrase-list"></div>
    </section>
    <section>
      <div class="pane-title">Phrase Detail</div>
      <div class="detail" id="detail"></div>
    </section>
  </main>
  <script>
    const state = { songs: [], selectedSong: null, selectedPhrase: null };
    const $ = (id) => document.getElementById(id);
    const noteLine = (phrase) => phrase.score_notes.map((n) => `${n.note}(${n.beats})`).join("  ");
    let audioContext = null;

    function noteToFrequency(note) {
      const match = note.match(/^([A-G])(#|b)?(\d)$/);
      if (!match) return 0;
      const base = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }[match[1]];
      const accidental = match[2] === '#' ? 1 : (match[2] === 'b' ? -1 : 0);
      const octave = Number(match[3]);
      const midi = (octave + 1) * 12 + base + accidental;
      return 440 * Math.pow(2, (midi - 69) / 12);
    }

    function playPhrase(phrase) {
      audioContext = audioContext || new AudioContext();
      const now = audioContext.currentTime + 0.04;
      phrase.notes.forEach((note) => {
        const frequency = noteToFrequency(note.note);
        if (!frequency) return;
        const start = now + note.start_ms / 1000;
        const duration = Math.max(0.06, note.duration_ms / 1000 * 0.88);
        const oscillator = audioContext.createOscillator();
        const gain = audioContext.createGain();
        oscillator.type = 'sine';
        oscillator.frequency.value = frequency;
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(0.16, start + 0.012);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
        oscillator.connect(gain).connect(audioContext.destination);
        oscillator.start(start);
        oscillator.stop(start + duration + 0.03);
      });
    }

    async function loadLibrary() {
      const response = await fetch('/library/songs');
      const body = await response.json();
      state.songs = body.songs;
      state.selectedSong = state.songs[0];
      state.selectedPhrase = state.selectedSong.phrases[0];
      $('status').textContent = `${state.songs.length} songs loaded`;
      renderSongs();
      renderTimeline();
      renderPhrases();
      await selectPhrase(state.selectedPhrase.phrase_id);
    }

    function renderSongs() {
      $('song-list').innerHTML = '';
      state.songs.forEach((song) => {
        const button = document.createElement('button');
        button.className = song === state.selectedSong ? 'active' : '';
        button.innerHTML = `<div class="song-title">${song.title}</div><div class="meta">song_id=${song.song_id} · ${song.bpm} BPM · ${song.melody_note_count} notes · ${song.phrase_count} phrases</div>`;
        button.onclick = async () => {
          state.selectedSong = song;
          state.selectedPhrase = song.phrases[0];
          renderSongs();
          renderTimeline();
          renderPhrases();
          await selectPhrase(state.selectedPhrase.phrase_id);
        };
        $('song-list').appendChild(button);
      });
    }

    function renderTimeline() {
      const selected = state.selectedPhrase;
      $('melody-timeline').innerHTML = '';
      state.selectedSong.melody_notes.forEach((note, index) => {
        const item = document.createElement('div');
        const inPhrase = selected && index >= selected.start_note_index && index < selected.end_note_index;
        item.className = `note-cell${inPhrase ? ' in-phrase' : ''}`;
        item.innerHTML = `<span class="idx">${index}</span><span class="note">${note.note}</span><span class="meta">${note.beats}</span>`;
        $('melody-timeline').appendChild(item);
      });
    }

    function renderPhrases() {
      $('phrase-list').innerHTML = '';
      state.selectedSong.phrases.forEach((phrase) => {
        const button = document.createElement('button');
        button.className = state.selectedPhrase && phrase.phrase_id === state.selectedPhrase.phrase_id ? 'active' : '';
        button.innerHTML = `<div class="phrase-id">${phrase.phrase_id}</div><div class="meta">${phrase.label} · notes ${phrase.start_note_index}-${phrase.end_note_index - 1} · next: ${phrase.next_phrase_id}</div>`;
        button.onclick = () => selectPhrase(phrase.phrase_id);
        $('phrase-list').appendChild(button);
      });
    }

    async function selectPhrase(phraseId) {
      const response = await fetch(`/library/phrases/${encodeURIComponent(phraseId)}`);
      const phrase = await response.json();
      state.selectedPhrase = phrase;
      renderTimeline();
      renderPhrases();
      renderDetail(phrase);
    }

    function renderDetail(phrase) {
      const notes = phrase.notes.map((note) => `<tr><td>${note.note}</td><td>${note.start_ms}</td><td>${note.duration_ms}</td><td>${note.velocity}</td></tr>`).join('');
      const response = phrase.response_phrase;
      $('detail').innerHTML = `
        <h2>${phrase.phrase_id}</h2>
        <div class="meta">${phrase.title} · ${phrase.label}</div>
        <div class="actions">
          <button onclick='playPhrase(state.selectedPhrase)'>Play phrase</button>
          <button onclick='playPhrase(state.selectedPhrase.response_phrase)'>Play response</button>
        </div>
        <div class="grid">
          <div class="metric"><span class="meta">song</span><b>${phrase.song_id}</b></div>
          <div class="metric"><span class="meta">bpm</span><b>${phrase.bpm}</b></div>
          <div class="metric"><span class="meta">duration</span><b>${phrase.duration_ms}</b></div>
          <div class="metric"><span class="meta">slice</span><b>${phrase.start_note_index}-${phrase.end_note_index - 1}</b></div>
        </div>
        <h3>Melody Slice</h3>
        <code>${noteLine({ score_notes: phrase.melody_slice })}</code>
        <h3>Score Notes</h3>
        <code>${noteLine(phrase)}</code>
        <h3>Response</h3>
        <code>${response.phrase_id}: ${noteLine(response)}</code>
        <h3>Runtime Notes</h3>
        <table>
          <thead><tr><th>note</th><th>start_ms</th><th>duration_ms</th><th>velocity</th></tr></thead>
          <tbody>${notes}</tbody>
        </table>`;
    }

    loadLibrary().catch((error) => {
      $('status').textContent = error.message;
      $('detail').textContent = error.stack || error.message;
    });
  </script>
</body>
</html>"""


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
    threshold_cap = 0.022 if peak_rms < 0.08 else 0.035
    threshold = max(0.006, min(threshold_cap, max(median_rms * 1.45, high_rms * 0.45, peak_rms * 0.08)))
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
    min_freq, max_freq = 120, 1120
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
        if corr > best_corr or (best_lag > 0 and corr >= best_corr * 0.92 and lag < best_lag):
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


def expand_phrase(notes: list[tuple[int, float]], bpm: int) -> list[int]:
    reference = []
    frames_per_beat = max(1, round((60000 / bpm) / 125))
    for midi, beats in notes:
        reference.extend([midi] * max(1, round(frames_per_beat * beats)))
    return reference


PHRASE_REFERENCES = {
    phrase_id: expand_phrase(notes, PHRASE_BPM[phrase_id])
    for phrase_id, notes in PHRASES.items()
}


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


def phrase_next_bar_delay(phrase_id: str, position_ms: int) -> int:
    beat_ms = PHRASE_BEAT_MS.get(phrase_id, BEAT_MS)
    bar_ms = beat_ms * 4
    if position_ms <= 0:
        return int(bar_ms)
    delay = int(bar_ms - (position_ms % int(bar_ms)))
    if delay < 250:
        delay += int(bar_ms)
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
    raw_observed_notes = [note for _, note in pitched]
    observed_notes = normalize_octave_glitches(raw_observed_notes)
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
        candidate_scores = []
        for candidate_notes in (raw_observed_notes, observed_notes):
            candidate_compact = compact_notes(candidate_notes)
            frame_score, transpose = score_phrase(candidate_notes, reference)
            shape_score = interval_score(candidate_compact, PHRASE_COMPACT[phrase_id])
            score = round(0.58 * frame_score + 0.42 * shape_score, 3)
            candidate_scores.append((score, frame_score, shape_score, transpose))
        score, frame_score, shape_score, transpose = max(candidate_scores, key=lambda value: value[0])
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

    twinkle_phrase_1_score = phrase_scores["phrase_1"]["score"]
    if upward_fifth_interval and twinkle_phrase_1_score >= max(0.34, best_score - 0.10):
        best_phrase_id = "phrase_1"
        best_score = max(best_score, 0.76)
        best_transpose = phrase_scores["phrase_1"]["transpose"]
        phrase_scores["phrase_1"]["score"] = round(best_score, 3)
    elif first_large_interval >= 4 and twinkle_phrase_1_score >= max(0.34, best_score - 0.10):
        best_phrase_id = "phrase_1"
        best_score = max(best_score, 0.74)
        best_transpose = phrase_scores["phrase_1"]["transpose"]
        phrase_scores["phrase_1"]["score"] = round(best_score, 3)

    if len(observed_intervals) >= 5:
        salut_opening_shape = (
            2 <= observed_intervals[0] <= 4
            and -4 <= observed_intervals[1] <= -2
            and -3 <= observed_intervals[2] <= -1
            and -3 <= observed_intervals[3] <= -1
            and 4 <= observed_intervals[4] <= 7
        )
        if salut_opening_shape and phrase_scores["salut_phrase_1"]["score"] >= 0.50:
            best_phrase_id = "salut_phrase_1"
            best_score = max(best_score, 0.72)
            best_transpose = phrase_scores["salut_phrase_1"]["transpose"]
            phrase_scores["salut_phrase_1"]["score"] = round(best_score, 3)

    sorted_scores = sorted((value["score"], phrase_id) for phrase_id, value in phrase_scores.items())
    second_score = sorted_scores[-2][0] if len(sorted_scores) >= 2 else 0.0
    score_margin = best_score - second_score

    beat_ms = PHRASE_BEAT_MS.get(best_phrase_id, BEAT_MS)
    position_ms = int(PHRASE_START_BEATS.get(best_phrase_id, 0) * beat_ms)
    position_at_record_end_ms = position_ms + max(0, audio_duration_ms - first_pitch_ms)
    beat_position = position_at_record_end_ms / beat_ms
    bar_index = int(beat_position // 4)
    beat_in_bar = beat_position % 4

    return {
        "song_id": PHRASE_SONG_ID.get(best_phrase_id, 0),
        "title": PHRASE_TITLE.get(best_phrase_id, ""),
        "confidence": round(float(best_score), 3),
        "position_ms": position_ms,
        "position_at_record_end_ms": int(position_at_record_end_ms),
        "bar_index": bar_index,
        "beat_in_bar": round(float(beat_in_bar), 2),
        "join_after_ms": phrase_next_bar_delay(best_phrase_id, position_at_record_end_ms),
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
        if path == "/library":
            self.send_html(library_page_html())
            return
        if path == "/library/songs":
            self.send_json(library_songs_response())
            return
        if path.startswith("/library/songs/"):
            song_id_text = urllib.parse.unquote(path.removeprefix("/library/songs/"))
            try:
                song_id = int(song_id_text)
            except ValueError:
                self.send_error(404)
                return
            songs = [song for song in library_songs_response()["songs"] if song["song_id"] == song_id]
            if not songs:
                self.send_error(404)
                return
            self.send_json(songs[0])
            return
        if path.startswith("/library/phrases/"):
            phrase_id = urllib.parse.unquote(path.removeprefix("/library/phrases/"))
            phrase = library_phrase_response(phrase_id)
            if phrase is None:
                self.send_error(404)
                return
            self.send_json(phrase)
            return
        if path == "/score":
            self.send_json(library_songs_response())
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

    def send_html(self, value: str, status: int = 200) -> None:
        self.send_bytes(value.encode("utf-8"), status, "text/html; charset=utf-8")

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
