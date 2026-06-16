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
    void play_track(const Song& song, const Track& track);
    void record(int16_t* samples, int sample_count);
    void stop();
    bool is_playing() const { return playing_; }

private:
    Box3AudioOutput audio_;
    bool playing_ = false;
};

const Song& twinkle_song();
const Track& select_track(const Song& song);
uint32_t bar_duration_ms(uint16_t bpm, uint8_t beats_per_bar = 4);

}  // namespace bandtoy
