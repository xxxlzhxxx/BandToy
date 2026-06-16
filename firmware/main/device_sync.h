#pragma once

#include <stdint.h>

#include "esp_err.h"
#include "song_runtime.h"

namespace bandtoy {

constexpr uint32_t kBandToySyncMagic = 0x42544F59;  // BTOY
constexpr uint8_t kBandToySyncVersion = 1;

struct SyncStartMessage {
    uint32_t magic;
    uint8_t version;
    uint16_t song_id;
    uint16_t bpm;
    uint8_t join_after_bars;
    uint32_t leader_uptime_ms;
};

using StartMessageHandler = void (*)(const SyncStartMessage& message);

class DeviceSync {
public:
    esp_err_t begin(StartMessageHandler handler);
    esp_err_t announce_start(const Song& song, uint8_t join_after_bars);

private:
    esp_err_t init_wifi();
    esp_err_t init_esp_now(StartMessageHandler handler);
};

}  // namespace bandtoy

