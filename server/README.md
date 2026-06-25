# BandToy Server

Tiny PoC server for two experiments:

- Legacy Twinkle phrase recognition.
- Musical Personality P0.1: MusicBox Fox listens to user text/audio emotion and
  replies only with motif variations.

Run:

```bash
python3 server.py --host 0.0.0.0 --port 8765
```

Health check:

```bash
curl http://127.0.0.1:8765/health
```

## Musical Personality P0.1

MusicBox Fox:

- `character_id`: `musicbox_fox`
- `instrument`: `music_box`
- base motif: `C5 E5 G5 E5`
- supported emotions: `happy`, `sad`, `comfort`, `sleep`, `curious`,
  `greeting`, `thinking`

Environment:

```bash
export ARK_API_KEY="..."
export ARK_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
export BANDTOY_LLM_MODEL="ep-20260219195713-2nbl9"

export VOLC_ASR_APP_ID="..."
export VOLC_ASR_ACCESS_TOKEN="..."
export VOLC_ASR_SECRET_KEY="..."  # Kept for console parity; websocket ASR uses the access token.
export VOLC_ASR_URL="wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"
export VOLC_ASR_RESOURCE_ID="volc.seedasr.sauc.duration"
export VOLC_ASR_LANGUAGE="zh-CN"
```

Do not commit these values. Local `.env` files are ignored.

ASR uses Volcengine's WebSocket binary protocol from the "大模型流式语音识别"
doc. The local server sends one `full client request` frame, then the recorded
ESP32 audio as one final `audio only request` frame. This matches the current
BandToy flow where the device records a short utterance and uploads it to the
local server.

Text emotion test:

```bash
curl -X POST http://127.0.0.1:8765/emotion \
  -H 'Content-Type: application/json' \
  -d '{"text":"我今天有点累"}'
```

ESP32-compatible personality mode:

```bash
export BANDTOY_RECOGNIZE_MODE="personality"

curl -X POST http://127.0.0.1:8765/recognize?mode=personality \
  -H 'Content-Type: audio/wav' \
  --data-binary @sample.wav
```

The ESP32 firmware can switch between the two recognition modes with the
BOOT/GPIO0 button. A press is accepted while the device is idle, listening, or
cooling down; the new mode is used by the next recognition upload:

- `song_chain`: posts to `/recognize?mode=twinkle` and plays the next Twinkle
  phrase returned by the server.
- `voice_emotion`: posts to `/recognize?mode=personality` and plays the
  MusicBox Fox motif variation selected from ASR + emotion intent.

The device logs the active mode before each upload:

```text
listening mode=song_chain until 1000 ms silence...
posting recognition mode=twinkle url=http://.../recognize?mode=twinkle

interaction mode switched: mode=voice_emotion server_mode=personality
listening mode=voice_emotion until 1000 ms silence...
posting recognition mode=personality url=http://.../recognize?mode=personality
```

Debug without ASR:

```bash
TEXT_B64=$(printf '我很好奇你在想什么' | base64)
curl -X POST http://127.0.0.1:8765/recognize?mode=personality \
  -H "X-BandToy-Text-Base64: $TEXT_B64" \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Personality score:

```bash
curl http://127.0.0.1:8765/personality/score
```

Response shape stays compatible with the firmware:

```json
{
  "recognized": true,
  "song_id": 1,
  "emotion": "comfort",
  "character_id": "musicbox_fox",
  "response_phrase_id": "variation_comfort",
  "response_phrase": {
    "phrase_id": "variation_comfort",
    "instrument": "music_box",
    "duration_ms": 4725,
    "notes": [
      {"note": "C5", "start_ms": 0, "duration_ms": 550, "velocity": 54}
    ]
  }
}
```

## Legacy Twinkle Recognition

This is not Shazam and not an AI model. It is a lightweight pitch-contour
matcher:

```text
audio
  -> frame-level pitch estimation
  -> MIDI-ish note contour
  -> sliding match against the built-in Twinkle reference
  -> confidence, position, and join delay
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

## Character Animation Pipeline

The same server also exposes a small Seedance-powered pipeline for generating
state animation clips for one BandToy character.

It creates one async Ark task per state, stores job metadata locally, then
downloads finished videos into `server/pipeline_data/assets/`.

Environment:

```bash
export ARK_API_KEY="..."
export ARK_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
export BANDTOY_SEEDANCE_MODEL="ep-20260302192238-nhf72"
```

Create a job:

```bash
curl -X POST http://127.0.0.1:8765/pipeline/animations \
  -H 'Content-Type: application/json' \
  -d '{
    "character": {
      "id": "panda",
      "name": "Panda",
      "description": "a tiny music-box panda companion with felt texture, round ears, and a small golden bell instrument"
    },
    "reference_image_url": "https://example.com/panda-reference.png",
    "states": {
      "waiting": {"label": "等待"},
      "listening": {"label": "聆听"},
      "playing": {"label": "演奏"}
    },
    "ratio": "1:1",
    "duration": 4,
    "resolution": "720p"
  }'
```

Poll and download finished assets:

```bash
curl http://127.0.0.1:8765/pipeline/jobs/{job_id}/poll
```

List jobs:

```bash
curl http://127.0.0.1:8765/pipeline/jobs
```

You can also pass `reference_image_path` for a local image. The service will
encode it as a data URL; if Ark rejects that input, use a reachable
`reference_image_url` instead.
