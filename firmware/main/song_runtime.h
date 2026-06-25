#pragma once

#include <stdint.h>

#include "box3_audio_output.h"

namespace bandtoy {

constexpr uint16_t kRest = 0;

struct NoteEvent {
    uint16_t frequency_hz;
    uint16_t beats_x100;
};

struct Track {
    const char* name;
    const NoteEvent* notes;
    uint16_t note_count;
};

struct PhraseNoteEvent {
    char note[4];
    uint32_t start_ms;
    uint32_t duration_ms;
    uint8_t velocity;
};

struct RuntimePhrase {
    char phrase_id[32];
    char instrument[16];
    PhraseNoteEvent notes[12];
    uint16_t note_count;
    uint32_t duration_ms;
};

struct Song {
    uint16_t song_id;
    const char* title;
    uint16_t bpm;
    Track melody;
    Track harmony;
};

class SongRuntime {
public:
    void begin();
    void play_ready_chime();
    void play_track(const Song& song, const Track& track);
    void play_phrase(const RuntimePhrase& phrase);
    void record(int16_t* samples, int sample_count);
    int record_until_silence(int16_t* samples,
                             int max_sample_count,
                             uint32_t silence_ms,
                             uint32_t max_wait_ms);
    void stop();
    bool is_playing() const { return playing_; }

private:
    Box3AudioOutput audio_;
    bool playing_ = false;
};

const Song& twinkle_song();
const Track& select_track(const Song& song);
const Track& twinkle_response_line_2();
uint32_t bar_duration_ms(uint16_t bpm, uint8_t beats_per_bar = 4);

}  // namespace bandtoy
