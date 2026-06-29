#include "recognition_client.h"

#include <string.h>
#include <algorithm>
#include <stdio.h>

#include "bandtoy_config.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "nvs_flash.h"
#include <stdlib.h>

namespace bandtoy {

namespace {
constexpr const char* TAG = "recognition_client";
constexpr EventBits_t kWifiConnectedBit = BIT0;
EventGroupHandle_t g_wifi_events = nullptr;

struct HttpResponseBuffer {
    char* data;
    int capacity;
    int length;
};

esp_err_t http_event_handler(esp_http_client_event_t* event) {
    if (event->event_id != HTTP_EVENT_ON_DATA || event->user_data == nullptr || event->data == nullptr) {
        return ESP_OK;
    }
    auto* buffer = static_cast<HttpResponseBuffer*>(event->user_data);
    const int copy_len = std::min(event->data_len, buffer->capacity - buffer->length - 1);
    if (copy_len > 0) {
        memcpy(buffer->data + buffer->length, event->data, copy_len);
        buffer->length += copy_len;
        buffer->data[buffer->length] = '\0';
    }
    return ESP_OK;
}

void wifi_event_handler(void*, esp_event_base_t event_base, int32_t event_id, void* event_data) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        auto* event = static_cast<wifi_event_sta_disconnected_t*>(event_data);
        xEventGroupClearBits(g_wifi_events, kWifiConnectedBit);
        ESP_LOGW(TAG, "wifi disconnected reason=%u, reconnecting",
                 event != nullptr ? static_cast<unsigned>(event->reason) : 0);
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(g_wifi_events, kWifiConnectedBit);
        ESP_LOGI(TAG, "wifi connected");
    }
}

bool parse_bool(const char* text, const char* key) {
    const char* found = strstr(text, key);
    if (found == nullptr) {
        return false;
    }
    const char* colon = strchr(found, ':');
    return colon != nullptr && strstr(colon, "true") != nullptr;
}

uint32_t parse_u32(const char* text, const char* key, uint32_t fallback) {
    const char* found = strstr(text, key);
    if (found == nullptr) {
        return fallback;
    }
    const char* colon = strchr(found, ':');
    if (colon == nullptr) {
        return fallback;
    }
    return static_cast<uint32_t>(strtoul(colon + 1, nullptr, 10));
}

float parse_float(const char* text, const char* key, float fallback) {
    const char* found = strstr(text, key);
    if (found == nullptr) {
        return fallback;
    }
    const char* colon = strchr(found, ':');
    if (colon == nullptr) {
        return fallback;
    }
    return strtof(colon + 1, nullptr);
}

bool parse_string(const char* text, const char* key, char* out, size_t out_size) {
    const char* found = strstr(text, key);
    if (found == nullptr || out == nullptr || out_size == 0) {
        return false;
    }
    const char* colon = strchr(found, ':');
    if (colon == nullptr) {
        return false;
    }
    const char* first_quote = strchr(colon, '"');
    if (first_quote == nullptr) {
        return false;
    }
    const char* second_quote = strchr(first_quote + 1, '"');
    if (second_quote == nullptr || second_quote <= first_quote + 1) {
        return false;
    }
    const size_t len = std::min(static_cast<size_t>(second_quote - first_quote - 1), out_size - 1);
    memcpy(out, first_quote + 1, len);
    out[len] = '\0';
    return true;
}

const char* parse_string_after(const char* text, const char* key, char* out, size_t out_size) {
    if (!parse_string(text, key, out, out_size)) {
        return nullptr;
    }
    const char* found = strstr(text, key);
    const char* colon = found != nullptr ? strchr(found, ':') : nullptr;
    const char* first_quote = colon != nullptr ? strchr(colon, '"') : nullptr;
    return first_quote != nullptr ? strchr(first_quote + 1, '"') : nullptr;
}

const char* parse_u32_after(const char* text, const char* key, uint32_t* out) {
    const char* found = strstr(text, key);
    if (found == nullptr || out == nullptr) {
        return nullptr;
    }
    const char* colon = strchr(found, ':');
    if (colon == nullptr) {
        return nullptr;
    }
    *out = static_cast<uint32_t>(strtoul(colon + 1, nullptr, 10));
    return colon + 1;
}

bool parse_response_phrase(const char* response, RuntimePhrase* phrase) {
    const char* root = strstr(response, "\"response_phrase\"");
    if (root == nullptr || phrase == nullptr) {
        return false;
    }
    memset(phrase, 0, sizeof(*phrase));
    parse_string(root, "\"phrase_id\"", phrase->phrase_id, sizeof(phrase->phrase_id));
    parse_string(root, "\"instrument\"", phrase->instrument, sizeof(phrase->instrument));
    parse_u32_after(root, "\"duration_ms\"", &phrase->duration_ms);

    const char* notes = strstr(root, "\"notes\"");
    if (notes == nullptr) {
        return phrase->phrase_id[0] != '\0';
    }

    const char* cursor = notes;
    while (phrase->note_count < sizeof(phrase->notes) / sizeof(phrase->notes[0])) {
        const char* note_key = strstr(cursor, "\"note\"");
        if (note_key == nullptr) {
            break;
        }
        PhraseNoteEvent& note = phrase->notes[phrase->note_count];
        const char* after_note = parse_string_after(note_key, "\"note\"", note.note, sizeof(note.note));
        if (after_note == nullptr) {
            break;
        }
        const char* after_start = parse_u32_after(after_note, "\"start_ms\"", &note.start_ms);
        const char* after_duration = parse_u32_after(after_start != nullptr ? after_start : after_note,
                                                     "\"duration_ms\"", &note.duration_ms);
        uint32_t velocity = 0;
        const char* after_velocity = parse_u32_after(after_duration != nullptr ? after_duration : after_note,
                                                     "\"velocity\"", &velocity);
        note.velocity = static_cast<uint8_t>(std::min<uint32_t>(velocity, 255));
        phrase->note_count += 1;
        cursor = after_velocity != nullptr ? after_velocity : after_note + 1;
    }

    return phrase->phrase_id[0] != '\0' && phrase->note_count > 0;
}

void build_recognition_url(const char* mode, char* out, size_t out_size) {
    if (out == nullptr || out_size == 0) {
        return;
    }
    const char* selected_mode = (mode != nullptr && mode[0] != '\0') ? mode : "twinkle";
    const char separator = strchr(kRecognitionServerUrl, '?') == nullptr ? '?' : '&';
    snprintf(out, out_size, "%s%cmode=%s", kRecognitionServerUrl, separator, selected_mode);
}
}  // namespace

void RecognitionClient::begin() {
    if (kWifiSsid[0] == '\0') {
        ESP_LOGW(TAG, "wifi is not configured; fill bandtoy_config.h");
        return;
    }

    g_wifi_events = xEventGroupCreate();
    esp_err_t nvs_result = nvs_flash_init();
    if (nvs_result == ESP_ERR_NVS_NO_FREE_PAGES || nvs_result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        nvs_result = nvs_flash_init();
    }
    ESP_ERROR_CHECK(nvs_result);
    ESP_ERROR_CHECK(esp_netif_init());
    esp_err_t event_loop_result = esp_event_loop_create_default();
    if (event_loop_result != ESP_ERR_INVALID_STATE) {
        ESP_ERROR_CHECK(event_loop_result);
    }
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, nullptr));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, nullptr));

    wifi_config_t wifi_config = {};
    strlcpy(reinterpret_cast<char*>(wifi_config.sta.ssid), kWifiSsid, sizeof(wifi_config.sta.ssid));
    strlcpy(reinterpret_cast<char*>(wifi_config.sta.password), kWifiPassword, sizeof(wifi_config.sta.password));
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));

    EventBits_t bits = xEventGroupWaitBits(g_wifi_events, kWifiConnectedBit, pdFALSE, pdFALSE, pdMS_TO_TICKS(15000));
    wifi_ready_ = (bits & kWifiConnectedBit) != 0;
    ESP_LOGI(TAG, "wifi_ready=%d", wifi_ready_);
}

RecognitionResult RecognitionClient::recognize(const int16_t* samples, int sample_count, uint32_t sample_rate) {
    return recognize(samples, sample_count, sample_rate, "twinkle");
}

RecognitionResult RecognitionClient::recognize(const int16_t* samples,
                                               int sample_count,
                                               uint32_t sample_rate,
                                               const char* mode) {
    RecognitionResult result = {
        .recognized = false,
        .song_id = 0,
        .confidence = 0.0f,
        .position_ms = 0,
        .position_at_record_end_ms = 0,
        .join_after_ms = 0,
        .has_response = false,
        .response_phrase_id = {},
        .response_delay_ms = 0,
        .response_phrase = {},
        .has_tts_audio = false,
        .tts_audio_url = {},
        .tts_audio_format = {},
        .spoken_text = {},
    };
    if (!wifi_ready_) {
        ESP_LOGW(TAG, "recognition skipped: wifi not ready");
        return result;
    }

    constexpr int kResponseCapacity = 4096;
    char* response = static_cast<char*>(calloc(kResponseCapacity, sizeof(char)));
    if (response == nullptr) {
        ESP_LOGE(TAG, "failed to allocate recognition response buffer");
        return result;
    }
    HttpResponseBuffer response_buffer = {
        .data = response,
        .capacity = kResponseCapacity,
        .length = 0,
    };
    char url[192] = {};
    build_recognition_url(mode, url, sizeof(url));
    esp_http_client_config_t config = {};
    config.url = url;
    config.method = HTTP_METHOD_POST;
    config.timeout_ms = 30000;
    config.event_handler = http_event_handler;
    config.user_data = &response_buffer;
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == nullptr) {
        free(response);
        return result;
    }

    char content_type[64] = {};
    snprintf(content_type, sizeof(content_type), "audio/x-raw; x-sample-rate=%lu", static_cast<unsigned long>(sample_rate));
    esp_http_client_set_header(client, "Content-Type", content_type);
    esp_http_client_set_post_field(client, reinterpret_cast<const char*>(samples), sample_count * sizeof(int16_t));
    ESP_LOGI(TAG, "posting recognition mode=%s url=%s", mode != nullptr ? mode : "twinkle", url);

    esp_err_t err = esp_http_client_perform(client);
    if (err == ESP_OK) {
        const int status = esp_http_client_get_status_code(client);
        ESP_LOGI(TAG, "recognize status=%d response_len=%d", status, response_buffer.length);
        if (response_buffer.length > 0) {
            ESP_LOGI(TAG, "recognize response: %s", response);
            result.recognized = parse_bool(response, "\"recognized\"");
            result.song_id = static_cast<uint16_t>(parse_u32(response, "\"song_id\"", 0));
            result.confidence = parse_float(response, "\"confidence\"", 0.0f);
            result.position_ms = parse_u32(response, "\"position_ms\"", 0);
            result.position_at_record_end_ms = parse_u32(response, "\"position_at_record_end_ms\"", 0);
            result.join_after_ms = parse_u32(response, "\"join_after_ms\"", 0);
            result.response_delay_ms = parse_u32(response, "\"response_delay_ms\"", 0);
            result.has_tts_audio = parse_string(response, "\"tts_audio_url\"", result.tts_audio_url,
                                                sizeof(result.tts_audio_url));
            parse_string(response, "\"tts_audio_format\"", result.tts_audio_format, sizeof(result.tts_audio_format));
            parse_string(response, "\"spoken_text\"", result.spoken_text, sizeof(result.spoken_text));
            result.has_response = parse_string(response, "\"response_phrase_id\"", result.response_phrase_id,
                                               sizeof(result.response_phrase_id));
            if (result.has_response) {
                result.has_response = parse_response_phrase(response, &result.response_phrase);
            }
        }
    } else {
        ESP_LOGE(TAG, "recognition request failed: %s", esp_err_to_name(err));
    }
    esp_http_client_cleanup(client);
    free(response);
    return result;
}

}  // namespace bandtoy
