#include "box3_audio_output.h"

#include <math.h>
#include <string.h>

#include "driver/i2s_std.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "pins.h"

namespace bandtoy {

namespace {
constexpr const char* TAG = "box3_audio_output";
constexpr float kTwoPi = 6.28318530717958647692f;
constexpr int kChunkSamples = 256;
constexpr int16_t kAmplitude = 10500;
constexpr int kAttackSamples = kBox3AudioSampleRate * 4 / 1000;
constexpr int kReleaseSamples = kBox3AudioSampleRate * 18 / 1000;
constexpr float kMusicBoxDecayMs = 760.0f;
constexpr uint8_t kEs8311Address = ES8311_CODEC_DEFAULT_ADDR;
constexpr uint8_t kEs7210Address = ES7210_CODEC_DEFAULT_ADDR;
constexpr int kOutputVolume = 88;
constexpr int kInputGain = 50;
}  // namespace

void Box3AudioOutput::begin() {
    if (ready_) {
        return;
    }

    i2c_master_bus_config_t i2c_bus_cfg = {};
    i2c_bus_cfg.i2c_port = static_cast<i2c_port_t>(1);
    i2c_bus_cfg.sda_io_num = kBox3AudioI2cSdaPin;
    i2c_bus_cfg.scl_io_num = kBox3AudioI2cSclPin;
    i2c_bus_cfg.clk_source = I2C_CLK_SRC_DEFAULT;
    i2c_bus_cfg.glitch_ignore_cnt = 7;
    i2c_bus_cfg.intr_priority = 0;
    i2c_bus_cfg.trans_queue_depth = 0;
    i2c_bus_cfg.flags.enable_internal_pullup = 1;
    ESP_ERROR_CHECK(i2c_new_master_bus(&i2c_bus_cfg, &i2c_bus_));

    i2s_chan_config_t chan_cfg = {};
    chan_cfg.id = I2S_NUM_0;
    chan_cfg.role = I2S_ROLE_MASTER;
    chan_cfg.dma_desc_num = 6;
    chan_cfg.dma_frame_num = 240;
    chan_cfg.auto_clear_after_cb = true;
    chan_cfg.auto_clear_before_cb = false;
    chan_cfg.intr_priority = 0;
    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, &tx_handle_, &rx_handle_));

    i2s_std_config_t std_cfg = {};
    std_cfg.clk_cfg.sample_rate_hz = kBox3AudioSampleRate;
    std_cfg.clk_cfg.clk_src = I2S_CLK_SRC_DEFAULT;
    std_cfg.clk_cfg.ext_clk_freq_hz = 0;
    std_cfg.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
    std_cfg.slot_cfg.data_bit_width = I2S_DATA_BIT_WIDTH_16BIT;
    std_cfg.slot_cfg.slot_bit_width = I2S_SLOT_BIT_WIDTH_AUTO;
    std_cfg.slot_cfg.slot_mode = I2S_SLOT_MODE_STEREO;
    std_cfg.slot_cfg.slot_mask = I2S_STD_SLOT_BOTH;
    std_cfg.slot_cfg.ws_width = I2S_DATA_BIT_WIDTH_16BIT;
    std_cfg.slot_cfg.ws_pol = false;
    std_cfg.slot_cfg.bit_shift = true;
    std_cfg.slot_cfg.left_align = true;
    std_cfg.slot_cfg.big_endian = false;
    std_cfg.slot_cfg.bit_order_lsb = false;
    std_cfg.gpio_cfg.mclk = kBox3AudioMclkPin;
    std_cfg.gpio_cfg.bclk = kBox3AudioBclkPin;
    std_cfg.gpio_cfg.ws = kBox3AudioWsPin;
    std_cfg.gpio_cfg.dout = kBox3AudioDoutPin;
    std_cfg.gpio_cfg.din = I2S_GPIO_UNUSED;
    std_cfg.gpio_cfg.invert_flags.mclk_inv = false;
    std_cfg.gpio_cfg.invert_flags.bclk_inv = false;
    std_cfg.gpio_cfg.invert_flags.ws_inv = false;
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(tx_handle_, &std_cfg));

    i2s_tdm_config_t tdm_cfg = {};
    tdm_cfg.clk_cfg.sample_rate_hz = kBox3AudioSampleRate;
    tdm_cfg.clk_cfg.clk_src = I2S_CLK_SRC_DEFAULT;
    tdm_cfg.clk_cfg.ext_clk_freq_hz = 0;
    tdm_cfg.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
    tdm_cfg.clk_cfg.bclk_div = 8;
    tdm_cfg.slot_cfg.data_bit_width = I2S_DATA_BIT_WIDTH_16BIT;
    tdm_cfg.slot_cfg.slot_bit_width = I2S_SLOT_BIT_WIDTH_AUTO;
    tdm_cfg.slot_cfg.slot_mode = I2S_SLOT_MODE_STEREO;
    tdm_cfg.slot_cfg.slot_mask = static_cast<i2s_tdm_slot_mask_t>(I2S_TDM_SLOT0 | I2S_TDM_SLOT1 | I2S_TDM_SLOT2 | I2S_TDM_SLOT3);
    tdm_cfg.slot_cfg.ws_width = I2S_TDM_AUTO_WS_WIDTH;
    tdm_cfg.slot_cfg.ws_pol = false;
    tdm_cfg.slot_cfg.bit_shift = true;
    tdm_cfg.slot_cfg.left_align = false;
    tdm_cfg.slot_cfg.big_endian = false;
    tdm_cfg.slot_cfg.bit_order_lsb = false;
    tdm_cfg.slot_cfg.skip_mask = false;
    tdm_cfg.slot_cfg.total_slot = I2S_TDM_AUTO_SLOT_NUM;
    tdm_cfg.gpio_cfg.mclk = kBox3AudioMclkPin;
    tdm_cfg.gpio_cfg.bclk = kBox3AudioBclkPin;
    tdm_cfg.gpio_cfg.ws = kBox3AudioWsPin;
    tdm_cfg.gpio_cfg.dout = I2S_GPIO_UNUSED;
    tdm_cfg.gpio_cfg.din = kBox3AudioDinPin;
    tdm_cfg.gpio_cfg.invert_flags.mclk_inv = false;
    tdm_cfg.gpio_cfg.invert_flags.bclk_inv = false;
    tdm_cfg.gpio_cfg.invert_flags.ws_inv = false;
    ESP_ERROR_CHECK(i2s_channel_init_tdm_mode(rx_handle_, &tdm_cfg));

    ESP_ERROR_CHECK(i2s_channel_enable(tx_handle_));
    ESP_ERROR_CHECK(i2s_channel_enable(rx_handle_));

    audio_codec_i2s_cfg_t i2s_cfg = {};
    i2s_cfg.port = I2S_NUM_0;
    i2s_cfg.rx_handle = rx_handle_;
    i2s_cfg.tx_handle = tx_handle_;
    data_if_ = audio_codec_new_i2s_data(&i2s_cfg);
    ESP_ERROR_CHECK(data_if_ != nullptr ? ESP_OK : ESP_FAIL);

    audio_codec_i2c_cfg_t i2c_cfg = {};
    i2c_cfg.port = static_cast<i2c_port_t>(1);
    i2c_cfg.addr = kEs8311Address;
    i2c_cfg.bus_handle = i2c_bus_;
    out_ctrl_if_ = audio_codec_new_i2c_ctrl(&i2c_cfg);
    ESP_ERROR_CHECK(out_ctrl_if_ != nullptr ? ESP_OK : ESP_FAIL);

    gpio_if_ = audio_codec_new_gpio();
    ESP_ERROR_CHECK(gpio_if_ != nullptr ? ESP_OK : ESP_FAIL);

    es8311_codec_cfg_t es8311_cfg = {};
    es8311_cfg.ctrl_if = out_ctrl_if_;
    es8311_cfg.gpio_if = gpio_if_;
    es8311_cfg.codec_mode = ESP_CODEC_DEV_WORK_MODE_DAC;
    es8311_cfg.pa_pin = kBox3AudioPaPin;
    es8311_cfg.use_mclk = true;
    es8311_cfg.hw_gain.pa_voltage = 5.0;
    es8311_cfg.hw_gain.codec_dac_voltage = 3.3;
    out_codec_if_ = es8311_codec_new(&es8311_cfg);
    ESP_ERROR_CHECK(out_codec_if_ != nullptr ? ESP_OK : ESP_FAIL);

    esp_codec_dev_cfg_t dev_cfg = {};
    dev_cfg.dev_type = ESP_CODEC_DEV_TYPE_OUT;
    dev_cfg.codec_if = out_codec_if_;
    dev_cfg.data_if = data_if_;
    output_dev_ = esp_codec_dev_new(&dev_cfg);
    ESP_ERROR_CHECK(output_dev_ != nullptr ? ESP_OK : ESP_FAIL);

    i2c_cfg.addr = kEs7210Address;
    in_ctrl_if_ = audio_codec_new_i2c_ctrl(&i2c_cfg);
    ESP_ERROR_CHECK(in_ctrl_if_ != nullptr ? ESP_OK : ESP_FAIL);

    es7210_codec_cfg_t es7210_cfg = {};
    es7210_cfg.ctrl_if = in_ctrl_if_;
    es7210_cfg.mic_selected = ES7210_SEL_MIC1 | ES7210_SEL_MIC2 | ES7210_SEL_MIC3 | ES7210_SEL_MIC4;
    in_codec_if_ = es7210_codec_new(&es7210_cfg);
    ESP_ERROR_CHECK(in_codec_if_ != nullptr ? ESP_OK : ESP_FAIL);

    dev_cfg.dev_type = ESP_CODEC_DEV_TYPE_IN;
    dev_cfg.codec_if = in_codec_if_;
    dev_cfg.data_if = data_if_;
    input_dev_ = esp_codec_dev_new(&dev_cfg);
    ESP_ERROR_CHECK(input_dev_ != nullptr ? ESP_OK : ESP_FAIL);

    esp_codec_dev_sample_info_t fs = {};
    fs.bits_per_sample = 16;
    fs.channel = 1;
    fs.channel_mask = 0;
    fs.sample_rate = kBox3AudioSampleRate;
    fs.mclk_multiple = 0;
    ESP_ERROR_CHECK(esp_codec_dev_open(output_dev_, &fs));
    ESP_ERROR_CHECK(esp_codec_dev_set_out_vol(output_dev_, kOutputVolume));

    esp_codec_dev_sample_info_t in_fs = {};
    in_fs.bits_per_sample = 16;
    in_fs.channel = 4;
    in_fs.channel_mask = ESP_CODEC_DEV_MAKE_CHANNEL_MASK(0);
    in_fs.sample_rate = kBox3AudioSampleRate;
    in_fs.mclk_multiple = 0;
    ESP_ERROR_CHECK(esp_codec_dev_open(input_dev_, &in_fs));
    ESP_ERROR_CHECK(esp_codec_dev_set_in_channel_gain(input_dev_, ESP_CODEC_DEV_MAKE_CHANNEL_MASK(0), kInputGain));

    ready_ = true;
    ESP_LOGI(TAG, "ESP32-S3-BOX-3 audio ready: %lu Hz volume=%d input_gain=%d",
             kBox3AudioSampleRate, kOutputVolume, kInputGain);
}

void Box3AudioOutput::play_tone(uint16_t frequency_hz, uint32_t duration_ms) {
    if (!ready_) {
        vTaskDelay(pdMS_TO_TICKS(duration_ms));
        return;
    }
    if (frequency_hz == 0) {
        silence(duration_ms);
        return;
    }

    const int32_t total_samples = static_cast<int32_t>((static_cast<uint64_t>(duration_ms) * kBox3AudioSampleRate) / 1000);
    int32_t remaining = total_samples;
    int32_t written = 0;
    int16_t samples[kChunkSamples];
    const float phase_step = kTwoPi * static_cast<float>(frequency_hz) / static_cast<float>(kBox3AudioSampleRate);
    phase_ = 0.0f;

    while (remaining > 0) {
        const int count = remaining > kChunkSamples ? kChunkSamples : remaining;
        for (int i = 0; i < count; ++i) {
            const int32_t sample_index = written + i;
            float attack = 1.0f;
            if (sample_index < kAttackSamples) {
                attack = static_cast<float>(sample_index) / static_cast<float>(kAttackSamples);
            }
            const float t_ms = static_cast<float>(sample_index) * 1000.0f / static_cast<float>(kBox3AudioSampleRate);
            float envelope = attack * expf(-t_ms / kMusicBoxDecayMs);
            const int32_t samples_to_end = total_samples - sample_index;
            if (samples_to_end < kReleaseSamples) {
                const float release = static_cast<float>(samples_to_end) / static_cast<float>(kReleaseSamples);
                envelope = envelope < release ? envelope : release;
            }

            const float tone = sinf(phase_) +
                               0.50f * sinf(phase_ * 2.0f) +
                               0.26f * sinf(phase_ * 3.0f) +
                               0.12f * sinf(phase_ * 5.0f);
            samples[i] = static_cast<int16_t>(tone * static_cast<float>(kAmplitude) * envelope * 0.58f);
            phase_ += phase_step;
            if (phase_ >= kTwoPi) {
                phase_ -= kTwoPi;
            }
        }
        write_samples(samples, count);
        written += count;
        remaining -= count;
    }
}

void Box3AudioOutput::silence(uint32_t duration_ms) {
    if (!ready_) {
        vTaskDelay(pdMS_TO_TICKS(duration_ms));
        return;
    }

    int32_t remaining = static_cast<int32_t>((static_cast<uint64_t>(duration_ms) * kBox3AudioSampleRate) / 1000);
    int16_t samples[kChunkSamples];
    memset(samples, 0, sizeof(samples));
    while (remaining > 0) {
        const int count = remaining > kChunkSamples ? kChunkSamples : remaining;
        write_samples(samples, count);
        remaining -= count;
    }
}

void Box3AudioOutput::record(int16_t* samples, int sample_count) {
    if (!ready_) {
        memset(samples, 0, sample_count * sizeof(int16_t));
        return;
    }
    ESP_ERROR_CHECK_WITHOUT_ABORT(esp_codec_dev_read(input_dev_, samples, sample_count * sizeof(int16_t)));
}

void Box3AudioOutput::write_samples(const int16_t* samples, int sample_count) {
    ESP_ERROR_CHECK_WITHOUT_ABORT(esp_codec_dev_write(output_dev_, const_cast<int16_t*>(samples), sample_count * sizeof(int16_t)));
}

}  // namespace bandtoy
