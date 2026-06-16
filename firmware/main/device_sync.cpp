#include "device_sync.h"

#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_now.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "nvs_flash.h"

namespace bandtoy {

namespace {

constexpr const char* TAG = "device_sync";
constexpr uint8_t kBroadcastMac[ESP_NOW_ETH_ALEN] = {
    0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
};

StartMessageHandler g_start_handler = nullptr;

void on_recv(const esp_now_recv_info_t* recv_info, const uint8_t* data, int len) {
    if (data == nullptr || len != sizeof(SyncStartMessage)) {
        return;
    }

    SyncStartMessage message = {};
    memcpy(&message, data, sizeof(message));
    if (message.magic != kBandToySyncMagic || message.version != kBandToySyncVersion) {
        return;
    }

    if (recv_info != nullptr && recv_info->src_addr != nullptr) {
        ESP_LOGI(TAG, "heard bandmate %02x:%02x:%02x:%02x:%02x:%02x song=%u bpm=%u join_after_bars=%u",
                 recv_info->src_addr[0], recv_info->src_addr[1], recv_info->src_addr[2],
                 recv_info->src_addr[3], recv_info->src_addr[4], recv_info->src_addr[5],
                 message.song_id, message.bpm, message.join_after_bars);
    }

    if (g_start_handler != nullptr) {
        g_start_handler(message);
    }
}

}  // namespace

esp_err_t DeviceSync::begin(StartMessageHandler handler) {
    ESP_ERROR_CHECK(init_wifi());
    ESP_ERROR_CHECK(init_esp_now(handler));
    return ESP_OK;
}

esp_err_t DeviceSync::announce_start(const Song& song, uint8_t join_after_bars) {
    SyncStartMessage message = {
        .magic = kBandToySyncMagic,
        .version = kBandToySyncVersion,
        .song_id = song.song_id,
        .bpm = song.bpm,
        .join_after_bars = join_after_bars,
        .leader_uptime_ms = static_cast<uint32_t>(esp_timer_get_time() / 1000),
    };

    return esp_now_send(kBroadcastMac, reinterpret_cast<const uint8_t*>(&message), sizeof(message));
}

esp_err_t DeviceSync::init_wifi() {
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

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE));

    uint8_t mac[6] = {};
    ESP_ERROR_CHECK(esp_read_mac(mac, ESP_MAC_WIFI_STA));
    ESP_LOGI(TAG, "wifi sta mac %02x:%02x:%02x:%02x:%02x:%02x",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    return ESP_OK;
}

esp_err_t DeviceSync::init_esp_now(StartMessageHandler handler) {
    g_start_handler = handler;

    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_register_recv_cb(on_recv));

    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, kBroadcastMac, ESP_NOW_ETH_ALEN);
    peer.channel = 1;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;

    esp_err_t add_peer_result = esp_now_add_peer(&peer);
    if (add_peer_result != ESP_ERR_ESPNOW_EXIST) {
        ESP_ERROR_CHECK(add_peer_result);
    }

    ESP_LOGI(TAG, "esp-now ready");
    return ESP_OK;
}

}  // namespace bandtoy

