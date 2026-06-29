#include "song_runtime.h"

#include "character_profile.h"
#include "pins.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_log.h"

#include <string.h>

namespace bandtoy {

namespace {

constexpr const char* TAG = "song_runtime";
constexpr int kMaxDownloadedAudioBytes = 768 * 1024;

struct DownloadBuffer {
    uint8_t* data;
    int capacity;
    int length;
};

struct PcmStreamContext {
    Box3AudioOutput* audio;
    uint8_t pending[2];
    int pending_count;
    int bytes_played;
};

esp_err_t audio_http_event_handler(esp_http_client_event_t* event) {
    if (event->event_id != HTTP_EVENT_ON_DATA || event->user_data == nullptr || event->data == nullptr) {
        return ESP_OK;
    }
    auto* buffer = static_cast<DownloadBuffer*>(event->user_data);
    if (buffer->length + event->data_len > buffer->capacity) {
        ESP_LOGW(TAG, "downloaded audio exceeds buffer: length=%d incoming=%d capacity=%d",
                 buffer->length, event->data_len, buffer->capacity);
        return ESP_FAIL;
    }
    memcpy(buffer->data + buffer->length, event->data, event->data_len);
    buffer->length += event->data_len;
    return ESP_OK;
}

esp_err_t pcm_stream_http_event_handler(esp_http_client_event_t* event) {
    if (event->event_id != HTTP_EVENT_ON_DATA || event->user_data == nullptr || event->data == nullptr) {
        return ESP_OK;
    }
    auto* context = static_cast<PcmStreamContext*>(event->user_data);
    const uint8_t* data = static_cast<const uint8_t*>(event->data);
    int length = event->data_len;
    if (context->pending_count == 1 && length > 0) {
        uint8_t pair[2] = {context->pending[0], data[0]};
        context->audio->play_pcm16(reinterpret_cast<const int16_t*>(pair), 1);
        context->bytes_played += 2;
        data += 1;
        length -= 1;
        context->pending_count = 0;
    }
    const int even_length = length - (length % 2);
    if (even_length > 0) {
        context->audio->play_pcm16(reinterpret_cast<const int16_t*>(data), even_length / 2);
        context->bytes_played += even_length;
    }
    if (length % 2 == 1) {
        context->pending[0] = data[length - 1];
        context->pending_count = 1;
    }
    return ESP_OK;
}

uint16_t read_le16(const uint8_t* data) {
    return static_cast<uint16_t>(data[0] | (data[1] << 8));
}

uint32_t read_le32(const uint8_t* data) {
    return static_cast<uint32_t>(data[0] | (data[1] << 8) | (data[2] << 16) | (data[3] << 24));
}

bool find_wav_pcm_data(const uint8_t* bytes,
                       int byte_count,
                       const int16_t** samples,
                       int* sample_count,
                       uint32_t* sample_rate) {
    if (bytes == nullptr || byte_count < 44 || memcmp(bytes, "RIFF", 4) != 0 || memcmp(bytes + 8, "WAVE", 4) != 0) {
        return false;
    }
    int offset = 12;
    bool saw_pcm_format = false;
    while (offset + 8 <= byte_count) {
        const uint8_t* chunk = bytes + offset;
        const uint32_t chunk_size = read_le32(chunk + 4);
        const int payload_offset = offset + 8;
        if (payload_offset + static_cast<int>(chunk_size) > byte_count) {
            return false;
        }
        if (memcmp(chunk, "fmt ", 4) == 0 && chunk_size >= 16) {
            const uint16_t format = read_le16(bytes + payload_offset);
            const uint16_t channels = read_le16(bytes + payload_offset + 2);
            const uint32_t rate = read_le32(bytes + payload_offset + 4);
            const uint16_t bits = read_le16(bytes + payload_offset + 14);
            saw_pcm_format = (format == 1 && channels == 1 && bits == 16);
            if (sample_rate != nullptr) {
                *sample_rate = rate;
            }
        } else if (memcmp(chunk, "data", 4) == 0) {
            if (!saw_pcm_format) {
                return false;
            }
            *samples = reinterpret_cast<const int16_t*>(bytes + payload_offset);
            *sample_count = static_cast<int>(chunk_size / sizeof(int16_t));
            return *sample_count > 0;
        }
        offset = payload_offset + static_cast<int>(chunk_size) + (chunk_size % 2);
    }
    return false;
}

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

bool SongRuntime::play_audio_url(const char* url) {
    if (url == nullptr || url[0] == '\0') {
        ESP_LOGW(TAG, "tts playback skipped: empty audio url");
        return false;
    }

    uint8_t* audio_bytes = static_cast<uint8_t*>(
        heap_caps_malloc(kMaxDownloadedAudioBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (audio_bytes == nullptr) {
        audio_bytes = static_cast<uint8_t*>(heap_caps_malloc(kMaxDownloadedAudioBytes, MALLOC_CAP_8BIT));
    }
    if (audio_bytes == nullptr) {
        ESP_LOGE(TAG, "failed to allocate tts download buffer");
        return false;
    }

    DownloadBuffer buffer = {
        .data = audio_bytes,
        .capacity = kMaxDownloadedAudioBytes,
        .length = 0,
    };
    esp_http_client_config_t config = {};
    config.url = url;
    config.method = HTTP_METHOD_GET;
    config.timeout_ms = 45000;
    config.event_handler = audio_http_event_handler;
    config.user_data = &buffer;
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == nullptr) {
        free(audio_bytes);
        return false;
    }

    ESP_LOGI(TAG, "downloading tts audio url=%s", url);
    const esp_err_t err = esp_http_client_perform(client);
    const int status = err == ESP_OK ? esp_http_client_get_status_code(client) : 0;
    esp_http_client_cleanup(client);
    if (err != ESP_OK || status != 200 || buffer.length <= 0) {
        ESP_LOGE(TAG, "tts audio download failed err=%s status=%d bytes=%d",
                 esp_err_to_name(err), status, buffer.length);
        free(audio_bytes);
        return false;
    }

    const int16_t* samples = nullptr;
    int sample_count = 0;
    uint32_t sample_rate = 0;
    if (!find_wav_pcm_data(audio_bytes, buffer.length, &samples, &sample_count, &sample_rate)) {
        ESP_LOGE(TAG, "tts audio is not 16-bit mono wav bytes=%d", buffer.length);
        free(audio_bytes);
        return false;
    }
    if (sample_rate != kBox3AudioSampleRate) {
        ESP_LOGW(TAG, "tts sample rate %lu differs from output %lu; playback speed may change",
                 static_cast<unsigned long>(sample_rate),
                 static_cast<unsigned long>(kBox3AudioSampleRate));
    }

    playing_ = true;
    ESP_LOGI(TAG, "%s starts tts audio bytes=%d samples=%d rate=%lu",
             kCharacter.display_name,
             buffer.length,
             sample_count,
             static_cast<unsigned long>(sample_rate));
    audio_.play_pcm16(samples, sample_count);
    audio_.silence(30);
    playing_ = false;
    free(audio_bytes);
    ESP_LOGI(TAG, "%s finished tts audio", kCharacter.display_name);
    return true;
}

bool SongRuntime::play_pcm_stream_url(const char* url) {
    if (url == nullptr || url[0] == '\0') {
        ESP_LOGW(TAG, "pcm stream skipped: empty audio url");
        return false;
    }

    PcmStreamContext context = {
        .audio = &audio_,
        .pending = {},
        .pending_count = 0,
        .bytes_played = 0,
    };
    esp_http_client_config_t config = {};
    config.url = url;
    config.method = HTTP_METHOD_GET;
    config.timeout_ms = 45000;
    config.event_handler = pcm_stream_http_event_handler;
    config.user_data = &context;
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == nullptr) {
        return false;
    }

    playing_ = true;
    ESP_LOGI(TAG, "%s starts pcm stream url=%s", kCharacter.display_name, url);
    const esp_err_t err = esp_http_client_perform(client);
    const int status = err == ESP_OK ? esp_http_client_get_status_code(client) : 0;
    esp_http_client_cleanup(client);
    if (context.pending_count == 1) {
        const uint8_t pair[2] = {context.pending[0], 0};
        audio_.play_pcm16(reinterpret_cast<const int16_t*>(pair), 1);
        context.bytes_played += 2;
    }
    audio_.silence(30);
    playing_ = false;
    if (err != ESP_OK || status != 200 || context.bytes_played <= 0) {
        ESP_LOGE(TAG, "pcm stream failed err=%s status=%d bytes=%d",
                 esp_err_to_name(err), status, context.bytes_played);
        return false;
    }
    ESP_LOGI(TAG, "%s finished pcm stream bytes=%d", kCharacter.display_name, context.bytes_played);
    return true;
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
