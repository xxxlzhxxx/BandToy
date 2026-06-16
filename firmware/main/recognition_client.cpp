#include "recognition_client.h"

#include <string.h>
#include <algorithm>

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

void wifi_event_handler(void*, esp_event_base_t event_base, int32_t event_id, void*) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "wifi disconnected, reconnecting");
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

    EventBits_t bits = xEventGroupWaitBits(g_wifi_events, kWifiConnectedBit, pdFALSE, pdFALSE, pdMS_TO_TICKS(15000));
    wifi_ready_ = (bits & kWifiConnectedBit) != 0;
    ESP_LOGI(TAG, "wifi_ready=%d", wifi_ready_);
}

RecognitionResult RecognitionClient::recognize(const int16_t* samples, int sample_count, uint32_t sample_rate) {
    RecognitionResult result = {
        .recognized = false,
        .song_id = 0,
        .confidence = 0.0f,
        .join_after_ms = 0,
    };
    if (!wifi_ready_) {
        ESP_LOGW(TAG, "recognition skipped: wifi not ready");
        return result;
    }

    char response[512] = {};
    HttpResponseBuffer response_buffer = {
        .data = response,
        .capacity = sizeof(response),
        .length = 0,
    };
    esp_http_client_config_t config = {};
    config.url = kRecognitionServerUrl;
    config.method = HTTP_METHOD_POST;
    config.timeout_ms = 10000;
    config.event_handler = http_event_handler;
    config.user_data = &response_buffer;
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == nullptr) {
        return result;
    }

    char content_type[64] = {};
    snprintf(content_type, sizeof(content_type), "audio/x-raw; x-sample-rate=%lu", static_cast<unsigned long>(sample_rate));
    esp_http_client_set_header(client, "Content-Type", content_type);
    esp_http_client_set_post_field(client, reinterpret_cast<const char*>(samples), sample_count * sizeof(int16_t));

    esp_err_t err = esp_http_client_perform(client);
    if (err == ESP_OK) {
        const int status = esp_http_client_get_status_code(client);
        ESP_LOGI(TAG, "recognize status=%d response_len=%d", status, response_buffer.length);
        if (response_buffer.length > 0) {
            ESP_LOGI(TAG, "recognize response: %s", response);
            result.recognized = parse_bool(response, "\"recognized\"");
            result.song_id = static_cast<uint16_t>(parse_u32(response, "\"song_id\"", 0));
            result.confidence = parse_float(response, "\"confidence\"", 0.0f);
            result.join_after_ms = parse_u32(response, "\"join_after_ms\"", 0);
        }
    } else {
        ESP_LOGE(TAG, "recognition request failed: %s", esp_err_to_name(err));
    }
    esp_http_client_cleanup(client);
    return result;
}

}  // namespace bandtoy
