#include "character_profile.h"
#include "device_sync.h"
#include "display_signals.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "life_signals.h"
#include "pins.h"
#include "recognition_client.h"
#include "song_runtime.h"

using namespace bandtoy;

namespace {

constexpr const char* TAG = "bandtoy";
constexpr uint32_t kMaxListenDurationMs = 10000;
constexpr uint32_t kNoSoundSessionTimeoutMs = 10000;
constexpr uint32_t kEndOfPhraseSilenceMs = 1000;
constexpr int kListenSamples = static_cast<int>((static_cast<uint64_t>(kMaxListenDurationMs) * kBox3AudioSampleRate) / 1000);
constexpr float kMinimumConfidence = 0.60f;
constexpr bool kManualCallResponseTest = false;
constexpr uint32_t kAutoRestartAfterNoSoundMs = 1000;
constexpr uint32_t kPostPlaybackCooldownMs = 1800;
constexpr uint32_t kFallbackResponseDelayMs = 500;

SongRuntime g_runtime;
LifeSignals g_life;
DisplaySignals g_display;
#if BANDTOY_ROLE_LEADER
RecognitionClient g_recognition;
#else
DeviceSync g_sync;
QueueHandle_t g_start_queue = nullptr;
#endif

enum class InteractionMode : uint8_t {
    kSongChain = 0,
    kVoiceEmotion,
    kVoiceChat,
};

volatile InteractionMode g_interaction_mode = InteractionMode::kSongChain;

const char* interaction_mode_name(InteractionMode mode) {
    switch (mode) {
        case InteractionMode::kSongChain:
            return "song_chain";
        case InteractionMode::kVoiceEmotion:
            return "voice_emotion";
        case InteractionMode::kVoiceChat:
            return "voice_chat";
        default:
            return "unknown";
    }
}

const char* recognition_mode_query(InteractionMode mode) {
    switch (mode) {
        case InteractionMode::kSongChain:
            return "twinkle";
        case InteractionMode::kVoiceEmotion:
            return "personality";
        case InteractionMode::kVoiceChat:
            return "chat";
        default:
            return "twinkle";
    }
}

bool wait_for_play_button_press() {
    while (true) {
        if (gpio_get_level(kPlayButtonPin) == 0) {
            vTaskDelay(pdMS_TO_TICKS(35));
            if (gpio_get_level(kPlayButtonPin) == 0) {
                ESP_LOGI(TAG, "play button pressed");
                while (gpio_get_level(kPlayButtonPin) == 0) {
                    vTaskDelay(pdMS_TO_TICKS(20));
                }
                vTaskDelay(pdMS_TO_TICKS(80));
                return true;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

bool consume_play_button_press() {
    if (gpio_get_level(kPlayButtonPin) != 0) {
        return false;
    }
    vTaskDelay(pdMS_TO_TICKS(35));
    if (gpio_get_level(kPlayButtonPin) != 0) {
        return false;
    }
    while (gpio_get_level(kPlayButtonPin) == 0) {
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    vTaskDelay(pdMS_TO_TICKS(80));
    return true;
}

void toggle_interaction_mode() {
    switch (g_interaction_mode) {
        case InteractionMode::kSongChain:
            g_interaction_mode = InteractionMode::kVoiceEmotion;
            break;
        case InteractionMode::kVoiceEmotion:
            g_interaction_mode = InteractionMode::kVoiceChat;
            break;
        case InteractionMode::kVoiceChat:
        default:
            g_interaction_mode = InteractionMode::kSongChain;
            break;
    }
    ESP_LOGI(TAG, "interaction mode switched: mode=%s server_mode=%s",
             interaction_mode_name(g_interaction_mode),
             recognition_mode_query(g_interaction_mode));
    g_display.success();
}

void init_play_button() {
    gpio_config_t io_conf = {};
    io_conf.pin_bit_mask = 1ULL << kPlayButtonPin;
    io_conf.mode = GPIO_MODE_INPUT;
    io_conf.pull_up_en = GPIO_PULLUP_ENABLE;
    io_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    io_conf.intr_type = GPIO_INTR_DISABLE;
    ESP_ERROR_CHECK(gpio_config(&io_conf));
}

bool should_play_response(const RecognitionResult& result, InteractionMode mode, const Song&) {
    if (!result.recognized || result.confidence < kMinimumConfidence) {
        return false;
    }
    if (mode == InteractionMode::kVoiceChat) {
        return result.has_tts_audio;
    }
    return result.has_response;
}

void log_audio_stats(const int16_t* samples, int sample_count) {
    int16_t peak = 0;
    double sum_squares = 0.0;
    for (int i = 0; i < sample_count; ++i) {
        const int16_t sample = samples[i];
        const int16_t magnitude = sample < 0 ? -sample : sample;
        if (magnitude > peak) {
            peak = magnitude;
        }
        sum_squares += static_cast<double>(sample) * static_cast<double>(sample);
    }
    const double value = sqrt(sum_squares / static_cast<double>(sample_count));
    ESP_LOGI(TAG, "recorded audio stats: samples=%d peak=%d rms=%.1f", sample_count, peak, value);
}

#if !BANDTOY_ROLE_LEADER
void on_start_message(const SyncStartMessage& message) {
    if (g_start_queue == nullptr) {
        return;
    }
    xQueueSend(g_start_queue, &message, 0);
}
#endif

#if BANDTOY_ROLE_LEADER
void mode_button_task(void*) {
    while (true) {
        if (consume_play_button_press()) {
            toggle_interaction_mode();
        }
        vTaskDelay(pdMS_TO_TICKS(30));
    }
}

void manual_call_response_task(void*) {
    const Song& song = twinkle_song();
    const Track& response = twinkle_response_line_2();

    vTaskDelay(pdMS_TO_TICKS(1500));
    ESP_LOGI(TAG, "%s is ready for manual call-and-response", kCharacter.display_name);

    while (true) {
        g_life.listening();
        g_display.idle();
        ESP_LOGI(TAG, "play Twinkle phrase_1 externally, then press BOOT/GPIO0 for ESP32 response");
        wait_for_play_button_press();

        g_display.success();
        ESP_LOGI(TAG, "heard phrase_1 finished; responding in %lu ms",
                 static_cast<unsigned long>(kFallbackResponseDelayMs));
        g_life.joining(kFallbackResponseDelayMs);

        g_life.playing();
        g_display.playing();
        g_runtime.play_track(song, response);
        g_life.idle();
        g_display.idle();

        vTaskDelay(pdMS_TO_TICKS(800));
    }
}

void leader_task(void*) {
    const Song& song = twinkle_song();
    int16_t* listen_buffer = static_cast<int16_t*>(
        heap_caps_malloc(kListenSamples * sizeof(int16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (listen_buffer == nullptr) {
        listen_buffer = static_cast<int16_t*>(heap_caps_malloc(kListenSamples * sizeof(int16_t), MALLOC_CAP_8BIT));
    }
    if (listen_buffer == nullptr) {
        ESP_LOGE(TAG, "failed to allocate listen buffer");
        vTaskDelete(nullptr);
        return;
    }

    vTaskDelay(pdMS_TO_TICKS(1500));
    ESP_LOGI(TAG, "%s is ready as listener", kCharacter.display_name);
    ESP_LOGI(TAG, "initial interaction mode: mode=%s server_mode=%s",
             interaction_mode_name(g_interaction_mode),
             recognition_mode_query(g_interaction_mode));
    g_runtime.play_ready_chime();

    while (true) {
        ESP_LOGI(TAG,
                 "auto continuous listener started; press BOOT/GPIO0 to switch mode for the next recognition; phrase ends after %lu ms silence, listening rests after %lu ms no sound",
                 static_cast<unsigned long>(kEndOfPhraseSilenceMs),
                 static_cast<unsigned long>(kNoSoundSessionTimeoutMs));

        while (true) {
            const InteractionMode mode = g_interaction_mode;
            g_life.listening();
            g_display.listening();
            ESP_LOGI(TAG, "listening mode=%s until %lu ms silence...",
                     interaction_mode_name(mode),
                     static_cast<unsigned long>(kEndOfPhraseSilenceMs));
            const int recorded_samples = g_runtime.record_until_silence(
                listen_buffer, kListenSamples, kEndOfPhraseSilenceMs, kNoSoundSessionTimeoutMs);
            if (recorded_samples <= 0) {
                ESP_LOGI(TAG, "continuous listening session stopped: no sound for %lu ms",
                         static_cast<unsigned long>(kNoSoundSessionTimeoutMs));
                g_life.idle();
                g_display.idle();
                vTaskDelay(pdMS_TO_TICKS(kAutoRestartAfterNoSoundMs));
                break;
            }
            log_audio_stats(listen_buffer, recorded_samples);
            g_display.recognizing();
            ESP_LOGI(TAG, "uploading recognition audio mode=%s server_mode=%s samples=%d duration_ms=%lu",
                     interaction_mode_name(mode),
                     recognition_mode_query(mode),
                     recorded_samples,
                     static_cast<unsigned long>((static_cast<uint64_t>(recorded_samples) * 1000) / kBox3AudioSampleRate));

            RecognitionResult result = g_recognition.recognize(
                listen_buffer, recorded_samples, kBox3AudioSampleRate, recognition_mode_query(mode));
            if (!should_play_response(result, mode, song)) {
                g_display.failure();
                ESP_LOGW(TAG, "not playing: mode=%s recognized=%d song_id=%u confidence=%.2f threshold=%.2f has_response=%d",
                         interaction_mode_name(mode),
                         result.recognized, result.song_id, result.confidence,
                         static_cast<double>(kMinimumConfidence), result.has_response);
                vTaskDelay(pdMS_TO_TICKS(500));
                continue;
            }

            g_display.success();
            const uint32_t response_delay_ms = result.response_delay_ms > 0 ? result.response_delay_ms : kFallbackResponseDelayMs;
            ESP_LOGI(TAG, "server selected mode=%s response_phrase_id=%s delay_ms=%lu notes=%u",
                     interaction_mode_name(mode),
                     result.response_phrase_id, static_cast<unsigned long>(response_delay_ms),
                     result.response_phrase.note_count);
            g_life.joining(response_delay_ms);
            g_life.playing();
            g_display.playing();
            if (mode == InteractionMode::kVoiceChat) {
                ESP_LOGI(TAG, "server chat reply: %s", result.spoken_text);
                if (!g_runtime.play_audio_url(result.tts_audio_url)) {
                    ESP_LOGW(TAG, "tts playback failed: url=%s", result.tts_audio_url);
                }
            } else {
                g_runtime.play_phrase(result.response_phrase);
            }
            vTaskDelay(pdMS_TO_TICKS(kPostPlaybackCooldownMs));
            g_life.listening();
            g_display.listening();
        }
    }
}
#else

void follower_task(void*) {
    const Song& song = twinkle_song();
    const Track& track = select_track(song);
    SyncStartMessage message = {};

    ESP_LOGI(TAG, "%s is listening for bandmates", kCharacter.display_name);
    while (true) {
        if (xQueueReceive(g_start_queue, &message, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        if (message.song_id != song.song_id || g_runtime.is_playing()) {
            continue;
        }

        g_life.listening();
        const uint32_t delay_ms = bar_duration_ms(message.bpm) * message.join_after_bars;
        g_life.joining(delay_ms);

        g_life.playing();
        g_runtime.play_track(song, track);
        g_life.idle();
    }
}
#endif

}  // namespace

extern "C" void app_main(void) {
    ESP_LOGI(TAG, "BandToy boot: %s / %s / %s",
             kCharacter.display_name, kCharacter.id, kCharacter.instrument);

    g_display.begin();
    g_life.begin();
    init_play_button();
    g_runtime.begin();

#if BANDTOY_ROLE_LEADER
    if (kManualCallResponseTest) {
        xTaskCreate(manual_call_response_task, "manual_response", 4096, nullptr, 5, nullptr);
    } else {
        g_recognition.begin();
        xTaskCreate(mode_button_task, "mode_button", 3072, nullptr, 6, nullptr);
        xTaskCreate(leader_task, "leader_task", 4096, nullptr, 5, nullptr);
    }
#else
    g_start_queue = xQueueCreate(4, sizeof(SyncStartMessage));
    ESP_ERROR_CHECK(g_sync.begin(on_start_message));
    xTaskCreate(follower_task, "follower_task", 4096, nullptr, 5, nullptr);
#endif
}
