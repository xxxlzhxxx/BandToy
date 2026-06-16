# BandToy Recognition Server

Tiny PoC server for recognizing only "Twinkle Twinkle Little Star".

This is not Shazam and not an AI model. It is a lightweight pitch-contour
matcher:

```text
audio
  -> frame-level pitch estimation
  -> MIDI-ish note contour
  -> sliding match against the built-in Twinkle reference
  -> confidence, position, and join delay
```

Run:

```bash
python3 server.py --host 0.0.0.0 --port 8765
```

Health check:

```bash
curl http://127.0.0.1:8765/health
```

The recognition endpoint accepts 16-bit PCM or WAV audio and returns a join hint:

```bash
curl -X POST \
  -H 'Content-Type: audio/wav' \
  --data-binary @sample.wav \
  http://127.0.0.1:8765/recognize
```

Response:

```json
{
  "song_id": 1,
  "title": "Twinkle Twinkle Little Star",
  "confidence": 0.82,
  "position_ms": 4300,
  "bar_index": 1,
  "beat_in_bar": 2.9,
  "join_after_ms": 700,
  "recognized": true,
  "debug": {
    "bytes": 192000,
    "samples": 64000,
    "rms": 0.05109,
    "pitched_frames": 32
  }
}
```

Field notes:

- `recognized`: true when confidence passes the current threshold.
- `confidence`: average contour similarity at the best match offset.
- `position_ms`: matched song position inside the uploaded recording.
- `bar_index`: zero-based bar index.
- `beat_in_bar`: beat position within the bar.
- `join_after_ms`: delay until the next bar according to the matched position.
- `debug.rms`: input energy after parsing/resampling.
- `debug.pitched_frames`: number of frames where pitch was detected.
