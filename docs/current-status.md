# Current Status

Last updated: 2026-06-19

## Implemented

### Phrase Runtime

- Single-machine call-and-response simulation.
- `NoteEvent`, `Phrase`, and `ResponseRule` data structures.
- `PhrasePlayer` for phrase playback state and note-event dispatch.
- `ResponseEngine` for phrase-to-response mapping.
- `InteractionRuntime` for scheduling phrase starts after phrase-finished
  events.
- Demo roles:
  - Character A: `music_box`
  - Character B: `violin`
- Demo flow:
  - A plays `phrase_1`
  - B responds with `response_1`
  - A plays `phrase_2`
  - B responds with `response_2`

### Hardware Target

- ESP32-S3-BOX-3 support.
- Built-in BOOT button on GPIO0 as the listening trigger.
- Built-in ES8311 speaker output.
- Built-in ES7210 microphone input.
- Built-in ILI9341 display output.

### Firmware

- Character profile for the current "Panda" prototype.
- Song runtime with BPM-based note scheduling.
- Twinkle Twinkle Little Star song model.
- Melody and harmony tracks.
- Music-box style synthesized tone with fast attack, harmonic overtones, and
  exponential decay.
- BOOT-triggered 4-second microphone recording.
- Audio statistics logging after recording.
- HTTP recognition client that uploads raw 16-bit PCM.
- Server-driven call-and-response: when the server recognizes `phrase_1`, it
  returns `response_phrase_id=response_1`, a short delay, and a response phrase
  payload. The firmware parses the returned phrase notes and plays them directly.
- Latency-compensated harmony joining when recognition succeeds. The firmware
  combines the server's estimated song position at recording end with local
  recognition round-trip time, then schedules playback at the next bar boundary.
- Simple state signals:
  - idle
  - listening
  - recognizing
  - success
  - failure
  - joining
  - playing

### Display

- Idle screen.
- Listening screen shown immediately after BOOT is pressed.
- Recognizing screen while the recording is being uploaded.
- Success screen when the server recognizes Twinkle.
- Failure screen when the server response is below threshold.
- Playing screen while the harmony track is sounding.

### Recognition Server

- Local Python HTTP server.
- `/health` endpoint.
- `/recognize` endpoint.
- 16-bit PCM and WAV parsing.
- Linear resampling to 16 kHz.
- Lightweight frame-level pitch estimation.
- Pitch contour matching against a built-in Twinkle reference.
- Response fields:
  - `heard_phrase_id`
  - `response_phrase_id`
  - `response_delay_ms`
  - `response_phrase`
  - `song_id`
  - `title`
  - `confidence`
  - `position_ms`
  - `bar_index`
  - `beat_in_bar`
  - `join_after_ms`
  - `recognized`
  - `debug`

### Test Assets

- `assets/reference_twinkle_96bpm.wav`: generated C-major, 96 BPM reference
  melody for repeatable recognition tests.
- `assets/twinkle_response_line_2.wav`: generated response phrase for the second
  line of Twinkle.

## Verified Locally

- Firmware builds with ESP-IDF 5.5.4.
- Firmware flashes to ESP32-S3-BOX-3 over `/dev/cu.usbmodem3101`.
- Display initializes successfully.
- WiFi connects to the local network when configured.
- ESP32 posts microphone audio to the server.
- Server returns `recognized: true` for the generated Twinkle reference audio.
- Server returns `response_phrase_id=response_1` for the first Twinkle phrase.
- Device waits for `response_delay_ms` and plays the second-line response track.

Example successful recognition:

```json
{
  "song_id": 1,
  "title": "Twinkle Twinkle Little Star",
  "confidence": 0.906,
  "position_ms": 1500,
  "position_at_record_end_ms": 5500,
  "bar_index": 2,
  "beat_in_bar": 0.8,
  "join_after_ms": 2000,
  "recognized": true,
  "heard_phrase_id": "phrase_1",
  "response_phrase_id": "response_1",
  "response_delay_ms": 500,
  "debug": {
    "bytes": 192000,
    "samples": 64000,
    "duration_ms": 4000,
    "rms": 0.0148,
    "pitched_frames": 32,
    "first_pitch_ms": 0
  }
}
```

Example device-side join calculation:

```text
recognized Twinkle confidence=0.91 position_ms=1500 record_end_position_ms=5500 server_join_ms=2000 recognition_roundtrip_ms=1110 compensated_join_ms=810
```

## Known Limitations

- Only Twinkle Twinkle Little Star is recognized.
- The recognition algorithm is a PoC contour matcher, not a full audio
  fingerprinting system.
- Join timing has basic local latency compensation, but it still assumes the
  external source keeps playing at the reference tempo and does not continuously
  follow drift after playback starts.
- The firmware still uses the default 1 MB factory app partition. The actual
  ESP32-S3-BOX-3 flash is larger, but the partition table should be updated
  before adding larger assets or more features.
- WiFi credentials and server URLs are local-only and should stay in
  `firmware/main/bandtoy_config.h`, which is ignored by Git.

## Next Candidates

- Add a custom 16 MB flash partition table.
- Add latency-compensated join timing.
- Improve recognition robustness for real external instruments.
- Move from Twinkle-only matching to a small multi-song library.
- Add MIDI import for song/track authoring.
- Restore or replace ESP-NOW multi-device joining once the microphone path feels
  good enough.
