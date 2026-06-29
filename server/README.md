# BandToy Server

Tiny PoC server for three experiments:

- Legacy Twinkle phrase recognition.
- Musical Personality P0.1: MusicBox Fox listens to user text/audio emotion and
  replies only with motif variations.
- Voice chat P0: listens to user speech, runs ASR + LLM + TTS, and returns a
  short spoken reply for the ESP32 to play.

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

export VOLC_TTS_APP_ID="..."
export VOLC_TTS_ACCESS_TOKEN="..."
export VOLC_TTS_URL="https://openspeech.bytedance.com/api/v3/tts/unidirectional"
export VOLC_TTS_RESOURCE_ID="seed-tts-2.0"
export VOLC_TTS_SPEAKER="zh_female_vv_uranus_bigtts"
export VOLC_TTS_SAMPLE_RATE="24000"
```

Do not commit these values. Local `.env` files are ignored.

For the current Volcengine console labels, use `Doubao_Seed_ASR_Streaming_2.0`
with `VOLC_ASR_RESOURCE_ID=volc.seedasr.sauc.duration`, and
`TTS-SeedTTS2.0` with `VOLC_TTS_RESOURCE_ID=seed-tts-2.0`.

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

The ESP32 firmware can switch between the three recognition modes with the
BOOT/GPIO0 button. A press is accepted while the device is idle, listening, or
cooling down; the new mode is used by the next recognition upload:

- `song_chain`: posts to `/recognize?mode=twinkle` and plays the next phrase
  returned by the server. The current phrase library includes Twinkle and a
  lowered one-octave PoC excerpt from Elgar's `Salut d'Amour`.
- `voice_emotion`: posts to `/recognize?mode=personality` and plays the
  MusicBox Fox motif variation selected from ASR + emotion intent.
- `voice_chat`: posts to `/recognize?mode=chat`, then downloads and plays the
  WAV returned by the server's ASR + LLM + TTS pipeline.

The device logs the active mode before each upload:

```text
listening mode=song_chain until 1000 ms silence...
posting recognition mode=twinkle url=http://.../recognize?mode=twinkle

interaction mode switched: mode=voice_emotion server_mode=personality
listening mode=voice_emotion until 1000 ms silence...
posting recognition mode=personality url=http://.../recognize?mode=personality

interaction mode switched: mode=voice_chat server_mode=chat
listening mode=voice_chat until 1000 ms silence...
posting recognition mode=chat url=http://.../recognize?mode=chat
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

Debug voice chat without ASR:

```bash
TEXT_B64=$(printf '你好小熊，今天有点累' | base64)
curl -X POST http://127.0.0.1:8765/recognize?mode=chat \
  -H "X-BandToy-Text-Base64: $TEXT_B64" \
  -H 'Content-Type: application/json' \
  -d '{}'
```

The chat response includes a short reply and a temporary WAV URL:

```json
{
  "recognized": true,
  "mode": "voice_chat",
  "heard_text": "你好小熊，今天有点累",
  "spoken_text": "我听见你说：你好小熊，今天有点累。我在这里陪你。",
  "tts_audio_url": "http://127.0.0.1:8765/tts/...",
  "tts_audio_format": "wav",
  "tts_sample_rate": 24000
}
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

## Song Chain Recognition

This is not Shazam and not an AI model. It is a lightweight pitch-contour
matcher:

```text
audio
  -> frame-level pitch estimation
  -> MIDI-ish note contour
  -> match against the built-in phrase library
  -> confidence, heard phrase, and next response phrase
```

The recognition endpoint accepts 16-bit PCM or WAV audio and returns the next
phrase to play:

```bash
curl -X POST \
  -H 'Content-Type: audio/wav' \
  --data-binary @sample.wav \
  http://127.0.0.1:8765/recognize?mode=twinkle
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

Deterministic local phrase checks:

```bash
python3 tools/bandtoy_test/play_twinkle_phrase.py phrase_1 \
  --no-play --out /tmp/bandtoy_twinkle_phrase_1.wav
curl -s -X POST -H 'Content-Type: audio/wav' \
  --data-binary @/tmp/bandtoy_twinkle_phrase_1.wav \
  'http://127.0.0.1:8765/recognize?mode=twinkle' | python3 -m json.tool

python3 tools/bandtoy_test/play_twinkle_phrase.py salut_phrase_1 \
  --no-play --out /tmp/bandtoy_salut_phrase_1.wav
curl -s -X POST -H 'Content-Type: audio/wav' \
  --data-binary @/tmp/bandtoy_salut_phrase_1.wav \
  'http://127.0.0.1:8765/recognize?mode=twinkle' | python3 -m json.tool
```

Library management P0:

```bash
python3 -u server/server.py --host 0.0.0.0 --port 8765
open http://127.0.0.1:8765/library
```

The P0 page is read-only. It shows the built-in song-chain library grouped by
song title, each song's original melody timeline, phrase slices on that melody,
next-phrase mapping, runtime note events, and response phrase details. The page
can preview the selected phrase or its response in the browser with WebAudio.
The backing JSON endpoints are:

```text
GET /library/songs
GET /library/songs/{song_id}
GET /library/phrases/{phrase_id}
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
