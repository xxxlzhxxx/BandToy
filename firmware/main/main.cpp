#include "character_profile.h"
#include "device_sync.h"
#include "display_signals.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
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
constexpr uint8_t kJoinAfterBars = 1;
constexpr uint32_t kListenDurationMs = 4000;
constexpr int kListenSamples = static_cast<int>((static_cast<uint64_t>(kListenDurationMs) * kBox3AudioSampleRate) / 1000);
constexpr float kMinimumConfidence = 0.45f;
constexpr uint32_t kMinimumJoinDelayMs = 250;
constexpr uint32_t kPlaybackStartupCompensationMs = 80;

SongRuntime g_runtime;
DeviceSync g_sync;
LifeSignals g_life;
DisplaySignals g_display;
QueueHandle_t g_start_queue = nullptr;
RecognitionClient g_recognition;

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

void init_play_button() {
    gpio_config_t io_conf = {};
    io_conf.pin_bit_mask = 1ULL << kPlayButtonPin;
    io_conf.mode = GPIO_MODE_INPUT;
    io_conf.pull_up_en = GPIO_PULLUP_ENABLE;
    io_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    io_conf.intr_type = GPIO_INTR_DISABLE;
    ESP_ERROR_CHECK(gpio_config(&io_conf));
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

uint32_t now_ms() {
    return static_cast<uint32_t>(esp_timer_get_time() / 1000ULL);
}

uint32_t latency_compensated_join_delay(uint32_t matched_position_ms,
                                        uint32_t elapsed_since_record_start_ms,
                                        uint16_t bpm) {
    const uint32_t bar_ms = bar_duration_ms(bpm);
    if (bar_ms == 0) {
        return 0;
    }
    const uint32_t estimated_now_ms = matched_position_ms + elapsed_since_record_start_ms + kPlaybackStartupCompensationMs;
    uint32_t delay_ms = bar_ms - (estimated_now_ms % bar_ms);
    if (delay_ms < kMinimumJoinDelayMs) {
        delay_ms += bar_ms;
    }
    return delay_ms;
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
void leader_task(void*) {
    const Song& song = twinkle_song();
    const Track& harmony = song.harmony;
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

    while (true) {
        g_life.listening();
        ESP_LOGI(TAG, "press BOOT/GPIO0, then play Twinkle externally for %lu ms",
                 static_cast<unsigned long>(kListenDurationMs));
        wait_for_play_button_press();

        g_display.listening();
        ESP_LOGI(TAG, "listening...");
        const uint32_t record_start_ms = now_ms();
        g_runtime.record(listen_buffer, kListenSamples);
        const uint32_t record_end_ms = now_ms();
        log_audio_stats(listen_buffer, kListenSamples);
        g_display.recognizing();
        ESP_LOGI(TAG, "uploading recognition audio");

        RecognitionResult result = g_recognition.recognize(listen_buffer, kListenSamples, kBox3AudioSampleRate);
        const uint32_t recognition_done_ms = now_ms();
        if (!result.recognized || result.song_id != song.song_id || result.confidence < kMinimumConfidence) {
            g_display.failure();
            ESP_LOGW(TAG, "not joining: recognized=%d song_id=%u confidence=%.2f",
                     result.recognized, result.song_id, result.confidence);
            g_life.idle();
            vTaskDelay(pdMS_TO_TICKS(1000));
            g_display.idle();
            continue;
        }

        g_display.success();
        const uint32_t elapsed_ms = recognition_done_ms - record_start_ms;
        const uint32_t compensated_join_ms = latency_compensated_join_delay(result.position_ms, elapsed_ms, song.bpm);
        ESP_LOGI(TAG,
                 "recognized Twinkle confidence=%.2f position_ms=%lu server_join_ms=%lu elapsed_ms=%lu compensated_join_ms=%lu",
                 result.confidence,
                 static_cast<unsigned long>(result.position_ms),
                 static_cast<unsigned long>(result.join_after_ms),
                 static_cast<unsigned long>(elapsed_ms),
                 static_cast<unsigned long>(compensated_join_ms));
        ESP_LOGI(TAG, "recording_ms=%lu recognition_roundtrip_ms=%lu",
                 static_cast<unsigned long>(record_end_ms - record_start_ms),
                 static_cast<unsigned long>(recognition_done_ms - record_end_ms));
        if (compensated_join_ms > 0) {
            g_life.joining(compensated_join_ms);
        }

        g_life.playing();
        g_display.playing();
        g_runtime.play_track(song, harmony);
        g_life.idle();
        g_display.idle();

        vTaskDelay(pdMS_TO_TICKS(1000));
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
    g_recognition.begin();
    xTaskCreate(leader_task, "leader_task", 4096, nullptr, 5, nullptr);
#else
    g_start_queue = xQueueCreate(4, sizeof(SyncStartMessage));
    ESP_ERROR_CHECK(g_sync.begin(on_start_message));
    xTaskCreate(follower_task, "follower_task", 4096, nullptr, 5, nullptr);
#endif
}
