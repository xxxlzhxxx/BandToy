# Phrase Runtime PoC

This directory contains the first BandToy call-and-response runtime.

The goal is not real-time ensemble synchronization. It is a tiny musical
conversation:

```text
A plays phrase_1
B waits a short moment
B plays response_1
A waits a short moment
A plays phrase_2
B waits a short moment
B plays response_2
```

The flow is driven by `Phrase` data and `ResponseRule` mappings, not by sleeps.

## Run

```bash
cd BandToy
c++ -std=c++17 phrase_runtime/phrase_runtime.cpp phrase_runtime/call_response_demo.cpp -o /tmp/bandtoy_phrase_demo
/tmp/bandtoy_phrase_demo
```

## Current Scope

- `music_box` phrases map to Character A.
- `violin` phrases map to Character B.
- Audio output is simulated with logs.
- Note events are logged so later ESP32 or desktop audio backends can consume
  the same phrase data.

## Expected Shape

The important high-level events look like this:

```text
[0ms] A starts phrase_1
[4200ms] A finished phrase_1
[4700ms] B starts response_1
[8200ms] B finished response_1
```

Additional note-level lines are printed between phrase start and finish events.
