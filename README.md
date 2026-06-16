# BandToy

BandToy is a proof-of-concept for small musical companions that listen, recognize
a melody, and join a shared performance.

The first prototype is deliberately narrow:

- One ESP32-S3-BOX-3 device.
- The user presses BOOT to start listening.
- The device records 4 seconds from the built-in microphone.
- A local Python server recognizes Twinkle Twinkle Little Star.
- The server returns confidence, song position, and a join delay.
- The device waits for the join delay and plays the harmony through the built-in
  speaker.
- The built-in display shows simple state signals: idle, listening, recognizing,
  success, failure, and playing.

The goal is not to prove a music engine or an AI stack. The goal is to answer a
product question:

> When one character starts playing and another character decides to join, does
> the moment feel alive?

## Directory Layout

```text
BandToy/
  assets/               Local test assets, including a reference Twinkle WAV
  docs/                 Product and architecture notes
  firmware/             ESP-IDF PoC firmware
  server/               Local recognition server
  tools/                Helper scripts
```

## Current Status

Implemented:

- ESP32-S3-BOX-3 audio output through ES8311.
- ESP32-S3-BOX-3 microphone recording through ES7210.
- BOOT/GPIO0-triggered 4-second listening window.
- HTTP upload of raw 16-bit PCM to the local recognition server.
- Twinkle-only pitch-contour matching on the server.
- Harmony playback after successful recognition.
- ILI9341 display state screens.
- Reference WAV for repeatable local tests.

Known limitations:

- Only Twinkle Twinkle Little Star is recognized.
- Join timing is musical but not yet fully latency-compensated. The server
  returns a join delay based on the matched position inside the recording; the
  firmware does not yet compensate for recording, upload, recognition, and
  playback startup latency.
- The firmware currently uses the default 1 MB app partition even though the
  ESP32-S3-BOX-3 flash is larger. The app is close to that partition limit.
- WiFi credentials and the recognition server URL are local configuration and
  are intentionally not committed.

## Firmware Quick Start

The firmware is an ESP-IDF project.

Create local config:

```bash
cd BandToy
cp firmware/main/bandtoy_config.h.example firmware/main/bandtoy_config.h
```

Edit `firmware/main/bandtoy_config.h` with your WiFi SSID, password, and local
recognition server URL.

Build and flash:

```bash
cd BandToy
cd firmware
idf.py -B build-leader -p /dev/cu.usbmodemXXXX flash
```

Monitor device logs:

```bash
idf.py -B build-leader -p /dev/cu.usbmodemXXXX monitor
```

On ESP-IDF shells that need setup first:

```bash
. ~/esp/esp-idf-v5.5.4/export.sh
```

## Recognition Server

Start the local server:

```bash
cd BandToy
python3 -u server/server.py --host 0.0.0.0 --port 8765 2>&1 | tee -a logs/recognition-server.log
```

Health check:

```bash
curl http://127.0.0.1:8765/health
```

Watch recognition logs:

```bash
tail -f logs/recognition-server.log
```

Play the reference melody:

```bash
afplay assets/reference_twinkle_96bpm.wav
```

## Current Hardware Assumptions

- ESP32-S3-BOX-3.
- Built-in ES8311 speaker output.
- Built-in ES7210 microphone input.
- Built-in ILI9341 display.
- BOOT button on GPIO0.

These pins are intentionally centralized in `firmware/main/pins.h`.
