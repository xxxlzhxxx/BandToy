# Musical Personality P0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Twinkle-first PoC path with a MusicBox Fox personality that hears or receives user text, infers emotion, and replies only with music.

**Architecture:** Keep ESP32 playback protocol unchanged: the server returns `recognized`, `response_phrase_id`, and `response_phrase.notes`. Add focused server modules for emotion routing, Volcengine LLM/ASR adapters, and motif variation generation. Keep the old Twinkle matcher available as legacy code while adding `/emotion` and an emotion mode for `/recognize`.

**Tech Stack:** Python stdlib HTTP server, Volcengine Ark OpenAI-compatible chat endpoint, configurable Volcengine ASR HTTP adapter, ESP32 existing runtime phrase parser.

---

### Task 1: MusicBox Fox Motif Engine

**Files:**
- Create: `server/music_personality.py`
- Test: `server/test_music_personality.py`

- [ ] **Step 1: Write tests for emotion parsing and variation generation**

Run: `python3 -m unittest server/test_music_personality.py`
Expected: FAIL because `server.music_personality` does not exist.

- [ ] **Step 2: Implement `Emotion`, `EmotionRouter`, and `CharacterMusicEngine`**

Create `server/music_personality.py` with `MusicBox Fox`, the base motif `C5 E5 G5 E5`, five emotion variations, and a fallback to `curious`.

- [ ] **Step 3: Verify tests pass**

Run: `python3 -m unittest server/test_music_personality.py`
Expected: PASS.

### Task 2: LLM Emotion Adapter

**Files:**
- Create: `server/emotion_ai.py`
- Test: `server/test_emotion_ai.py`

- [ ] **Step 1: Write tests for robust LLM JSON parsing**

Run: `python3 -m unittest server/test_emotion_ai.py`
Expected: FAIL because `server.emotion_ai` does not exist.

- [ ] **Step 2: Implement Ark chat adapter and parser**

Read `ARK_API_KEY`, `ARK_BASE_URL`, and `BANDTOY_LLM_MODEL`. Return normalized `emotion`, `energy`, `intent`, and source text. Fall back to deterministic keyword routing when credentials are absent or the API errors.

- [ ] **Step 3: Verify tests pass**

Run: `python3 -m unittest server/test_emotion_ai.py`
Expected: PASS.

### Task 3: ASR Adapter

**Files:**
- Modify: `server/emotion_ai.py`
- Test: `server/test_emotion_ai.py`

- [ ] **Step 1: Write tests for ASR disabled/configurable behavior**

Run: `python3 -m unittest server/test_emotion_ai.py`
Expected: FAIL until ASR config handling exists.

- [ ] **Step 2: Implement configurable ASR client**

Read `VOLC_ASR_APP_ID`, `VOLC_ASR_ACCESS_TOKEN`, `VOLC_ASR_SECRET_KEY`, and optional `VOLC_ASR_URL`. If `VOLC_ASR_URL` is missing, return a clear disabled result instead of guessing an endpoint.

- [ ] **Step 3: Verify tests pass**

Run: `python3 -m unittest server/test_emotion_ai.py`
Expected: PASS.

### Task 4: Server Routes

**Files:**
- Modify: `server/server.py`
- Test: `server/test_personality_server.py`

- [ ] **Step 1: Write route tests**

Test `/emotion` with JSON text and `/recognize?mode=personality` with fake ASR text injected through the adapter.

- [ ] **Step 2: Implement routes**

Add `/emotion`, `/personality/score`, and `/recognize?mode=personality`. Preserve `/recognize` legacy Twinkle mode unless `BANDTOY_RECOGNIZE_MODE=personality`.

- [ ] **Step 3: Verify tests pass**

Run: `python3 -m unittest discover server -p 'test_*.py'`
Expected: PASS.

### Task 5: Firmware Integration Switch

**Files:**
- Modify: `firmware/main/main.cpp` only if needed.

- [ ] **Step 1: Prefer no firmware change**

Because the current firmware already uploads audio and plays `response_phrase`, first test against `/recognize` with `BANDTOY_RECOGNIZE_MODE=personality`.

- [ ] **Step 2: Build and flash only if needed**

Run: `. /Users/lzh_claw/esp/esp-idf-v5.5.4/export.sh && idf.py -B build-leader build`.
Expected: PASS if firmware changes are required.

### Task 6: Manual Verification

**Files:**
- Modify: `server/README.md`

- [ ] **Step 1: Document local env vars without secrets**

Document `ARK_API_KEY`, `BANDTOY_LLM_MODEL`, `VOLC_ASR_APP_ID`, `VOLC_ASR_ACCESS_TOKEN`, `VOLC_ASR_SECRET_KEY`, `VOLC_ASR_URL`, and `BANDTOY_RECOGNIZE_MODE`.

- [ ] **Step 2: Run text emotion smoke tests**

Run `/emotion` for happy, sad, comfort, sleep, and curious Chinese/English inputs. Expected: different `response_phrase_id` values and notes that share the MusicBox Fox motif.

- [ ] **Step 3: Run server tests**

Run: `python3 -m unittest discover server -p 'test_*.py'`
Expected: PASS.
