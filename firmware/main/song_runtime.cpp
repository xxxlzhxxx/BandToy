#include "song_runtime.h"

#include "character_profile.h"
#include "esp_log.h"

namespace bandtoy {

namespace {

constexpr const char* TAG = "song_runtime";

uint16_t note_to_frequency_hz(const char* note) {
    if (note == nullptr || note[0] == '\0') {
        return kRest;
    }
    int semitone = 0;
    switch (note[0]) {
        case 'C': semitone = 0; break;
        case 'D': semitone = 2; break;
        case 'E': semitone = 4; break;
        case 'F': semitone = 5; break;
        case 'G': semitone = 7; break;
        case 'A': semitone = 9; break;
        case 'B': semitone = 11; break;
        default: return kRest;
    }

    int cursor = 1;
    if (note[cursor] == '#') {
        semitone += 1;
        cursor += 1;
    } else if (note[cursor] == 'b') {
        semitone -= 1;
        cursor += 1;
    }

    const int octave = note[cursor] >= '0' && note[cursor] <= '9' ? note[cursor] - '0' : 4;
    const int midi = (octave + 1) * 12 + semitone;
    switch (midi) {
        case 55: return 196;   // G3
        case 57: return 220;   // A3
        case 59: return 247;   // B3
        case 60: return 262;   // C4
        case 61: return 277;   // C#4/Db4
        case 62: return 294;   // D4
        case 63: return 311;   // D#4/Eb4
        case 64: return 330;   // E4
        case 65: return 349;   // F4
        case 66: return 370;   // F#4/Gb4
        case 67: return 392;   // G4
        case 68: return 415;   // G#4/Ab4
        case 69: return 440;   // A4
        case 70: return 466;   // A#4/Bb4
        case 71: return 494;   // B4
        case 72: return 523;   // C5
        case 73: return 554;   // C#5/Db5
        case 74: return 587;   // D5
        case 75: return 622;   // D#5/Eb5
        case 76: return 659;   // E5
        case 77: return 698;   // F5
        case 78: return 740;   // F#5/Gb5
        case 79: return 784;   // G5
        case 80: return 831;   // G#5/Ab5
        case 81: return 880;   // A5
        case 82: return 932;   // A#5/Bb5
        case 83: return 988;   // B5
        case 84: return 1047;  // C6
        default: return kRest;
    }
}

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

void SongRuntime::play_ready_chime() {
    ESP_LOGI(TAG, "%s plays ready chime", kCharacter.display_name);
    audio_.play_tone(1000, 1000);
    audio_.silence(120);
    audio_.play_tone(1175, 360);
    audio_.silence(80);
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

void SongRuntime::play_phrase(const RuntimePhrase& phrase) {
    ESP_LOGI(TAG, "%s starts phrase %s / %s notes=%u",
             kCharacter.display_name, phrase.phrase_id, phrase.instrument, phrase.note_count);
    playing_ = true;
    uint32_t cursor_ms = 0;

    for (uint16_t i = 0; i < phrase.note_count && playing_; ++i) {
        const PhraseNoteEvent& note = phrase.notes[i];
        if (note.start_ms > cursor_ms) {
            audio_.silence(note.start_ms - cursor_ms);
            cursor_ms = note.start_ms;
        }
        const uint16_t frequency_hz = note_to_frequency_hz(note.note);
        const uint32_t tone_ms = note.duration_ms * 88 / 100;
        const uint32_t gap_ms = note.duration_ms - tone_ms;
        audio_.play_tone(frequency_hz, tone_ms);
        audio_.silence(gap_ms);
        cursor_ms += note.duration_ms;
    }

    if (phrase.duration_ms > cursor_ms) {
        audio_.silence(phrase.duration_ms - cursor_ms);
    }
    audio_.silence(20);
    playing_ = false;
    ESP_LOGI(TAG, "%s finished phrase %s", kCharacter.display_name, phrase.phrase_id);
}

void SongRuntime::record(int16_t* samples, int sample_count) {
    audio_.record(samples, sample_count);
}

int SongRuntime::record_until_silence(int16_t* samples,
                                      int max_sample_count,
                                      uint32_t silence_ms,
                                      uint32_t max_wait_ms) {
    return audio_.record_until_silence(samples, max_sample_count, silence_ms, max_wait_ms);
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
