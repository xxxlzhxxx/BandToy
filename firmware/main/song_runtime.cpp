#include "song_runtime.h"

#include "character_profile.h"
#include "esp_log.h"

namespace bandtoy {

namespace {

constexpr const char* TAG = "song_runtime";

constexpr NoteEvent kTwinkleMelody[] = {
    {262, 100}, {262, 100}, {392, 100}, {392, 100}, {440, 100}, {440, 100}, {392, 200},
    {349, 100}, {349, 100}, {330, 100}, {330, 100}, {294, 100}, {294, 100}, {262, 200},
    {392, 100}, {392, 100}, {349, 100}, {349, 100}, {330, 100}, {330, 100}, {294, 200},
    {392, 100}, {392, 100}, {349, 100}, {349, 100}, {330, 100}, {330, 100}, {294, 200},
    {262, 100}, {262, 100}, {392, 100}, {392, 100}, {440, 100}, {440, 100}, {392, 200},
    {349, 100}, {349, 100}, {330, 100}, {330, 100}, {294, 100}, {294, 100}, {262, 200},
};

constexpr NoteEvent kTwinkleHarmony[] = {
    {kRest, 400},
    {196, 200}, {220, 200}, {196, 400},
    {175, 200}, {165, 200}, {147, 200}, {131, 200},
    {196, 200}, {175, 200}, {165, 200}, {147, 200},
    {196, 200}, {175, 200}, {165, 200}, {147, 200},
    {131, 200}, {196, 200}, {220, 200}, {196, 200},
    {175, 200}, {165, 200}, {147, 200}, {131, 200},
};

constexpr NoteEvent kTwinkleResponseLine2[] = {
    {349, 100}, {349, 100}, {330, 100}, {330, 100}, {294, 100}, {294, 100}, {262, 200},
};

constexpr Track kTwinkleResponseTrack = {
    .name = "response_line_2",
    .notes = kTwinkleResponseLine2,
    .note_count = sizeof(kTwinkleResponseLine2) / sizeof(kTwinkleResponseLine2[0]),
};

constexpr Song kTwinkle = {
    .song_id = 1,
    .title = "Twinkle Twinkle Little Star",
    .bpm = 96,
    .melody = {
        .name = "melody",
        .notes = kTwinkleMelody,
        .note_count = sizeof(kTwinkleMelody) / sizeof(kTwinkleMelody[0]),
    },
    .harmony = {
        .name = "harmony",
        .notes = kTwinkleHarmony,
        .note_count = sizeof(kTwinkleHarmony) / sizeof(kTwinkleHarmony[0]),
    },
};

}  // namespace

void SongRuntime::begin() {
    audio_.begin();
}

void SongRuntime::play_track(const Song& song, const Track& track) {
    ESP_LOGI(TAG, "%s starts %s / %s at %u BPM", kCharacter.display_name, song.title, track.name, song.bpm);
    playing_ = true;
    const uint32_t beat_ms = 60000 / song.bpm;

    for (uint16_t i = 0; i < track.note_count && playing_; ++i) {
        const NoteEvent& note = track.notes[i];
        const uint32_t duration_ms = (beat_ms * note.beats_x100) / 100;
        audio_.play_tone(note.frequency_hz, duration_ms * 88 / 100);
        audio_.silence(duration_ms * 12 / 100);
    }

    audio_.silence(20);
    playing_ = false;
    ESP_LOGI(TAG, "%s finished %s", kCharacter.display_name, track.name);
}

void SongRuntime::record(int16_t* samples, int sample_count) {
    audio_.record(samples, sample_count);
}

void SongRuntime::stop() {
    playing_ = false;
    audio_.silence(20);
}

const Song& twinkle_song() {
    return kTwinkle;
}

const Track& select_track(const Song& song) {
    if (kCharacter.track_role == TrackRole::kMelody) {
        return song.melody;
    }
    return song.harmony;
}

const Track& twinkle_response_line_2() {
    return kTwinkleResponseTrack;
}

uint32_t bar_duration_ms(uint16_t bpm, uint8_t beats_per_bar) {
    return (60000 / bpm) * beats_per_bar;
}

}  // namespace bandtoy
