#pragma once

#include <stdint.h>

#include "driver/i2c_master.h"
#include "driver/i2s_std.h"
#include "esp_codec_dev.h"
#include "esp_codec_dev_defaults.h"

namespace bandtoy {

class Box3AudioOutput {
public:
    void begin();
    void play_tone(uint16_t frequency_hz, uint32_t duration_ms);
    void silence(uint32_t duration_ms);
    void record(int16_t* samples, int sample_count);
    int record_until_silence(int16_t* samples,
                             int max_sample_count,
                             uint32_t silence_ms,
                             uint32_t max_wait_ms);

private:
    void init_input();
    void write_samples(const int16_t* samples, int sample_count);

    bool ready_ = false;
    bool input_ready_ = false;
    float phase_ = 0.0f;
    i2c_master_bus_handle_t i2c_bus_ = nullptr;
    i2s_chan_handle_t tx_handle_ = nullptr;
    i2s_chan_handle_t rx_handle_ = nullptr;
    const audio_codec_data_if_t* data_if_ = nullptr;
    const audio_codec_ctrl_if_t* out_ctrl_if_ = nullptr;
    const audio_codec_ctrl_if_t* in_ctrl_if_ = nullptr;
    const audio_codec_gpio_if_t* gpio_if_ = nullptr;
    const audio_codec_if_t* out_codec_if_ = nullptr;
    const audio_codec_if_t* in_codec_if_ = nullptr;
    esp_codec_dev_handle_t output_dev_ = nullptr;
    esp_codec_dev_handle_t input_dev_ = nullptr;
};

}  // namespace bandtoy
