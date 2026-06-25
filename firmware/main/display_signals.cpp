#include "display_signals.h"

#include <stdio.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_heap_caps.h"
#include "esp_lcd_ili9341.h"
#include "esp_lcd_panel_io.h"
#include "esp_log.h"
#include "esp_spiffs.h"
#include "pins.h"

namespace bandtoy {

namespace {
constexpr const char* TAG = "display_signals";
constexpr const char* kAssetsBasePath = "/assets";
constexpr int kAnimationWidth = kBox3DisplayWidth;
constexpr int kAnimationHeight = kBox3DisplayHeight;
constexpr int kAnimationRowsPerChunk = 16;
constexpr int kAnimationFrames = 8;
constexpr uint32_t kAnimationFrameDelayMs = 500;
constexpr uint16_t kBlack = 0x0000;
constexpr uint16_t kIdleBlue = 0x03BF;
constexpr uint16_t kListenBlue = 0x045F;
constexpr uint16_t kWhite = 0xFFFF;
constexpr uint16_t kGreen = 0x07E0;
constexpr uint16_t kRed = 0xF800;
constexpr uint16_t kAmber = 0xFD20;

static const ili9341_lcd_init_cmd_t kVendorInit[] = {
    {0xC8, (uint8_t[]){0xFF, 0x93, 0x42}, 3, 0},
    {0xC0, (uint8_t[]){0x0E, 0x0E}, 2, 0},
    {0xC5, (uint8_t[]){0xD0}, 1, 0},
    {0xC1, (uint8_t[]){0x02}, 1, 0},
    {0xB4, (uint8_t[]){0x02}, 1, 0},
    {0xE0, (uint8_t[]){0x00, 0x03, 0x08, 0x06, 0x13, 0x09, 0x39, 0x39, 0x48, 0x02, 0x0a, 0x08, 0x17, 0x17, 0x0F}, 15, 0},
    {0xE1, (uint8_t[]){0x00, 0x28, 0x29, 0x01, 0x0d, 0x03, 0x3f, 0x33, 0x52, 0x04, 0x0f, 0x0e, 0x37, 0x38, 0x0F}, 15, 0},
    {0xB1, (uint8_t[]){0x00, 0x1B}, 2, 0},
    {0x36, (uint8_t[]){0x08}, 1, 0},
    {0x3A, (uint8_t[]){0x55}, 1, 0},
    {0xB7, (uint8_t[]){0x06}, 1, 0},
    {0x11, (uint8_t[]){0}, 0x80, 0},
    {0x29, (uint8_t[]){0}, 0x80, 0},
    {0, (uint8_t[]){0}, 0xff, 0},
};

bool check(esp_err_t err, const char* what) {
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "%s failed: %s", what, esp_err_to_name(err));
        return false;
    }
    return true;
}

}  // namespace

void DisplaySignals::begin() {
    draw_lock_ = xSemaphoreCreateMutex();
    gpio_config_t backlight = {};
    backlight.pin_bit_mask = 1ULL << kBox3DisplayBacklightPin;
    backlight.mode = GPIO_MODE_OUTPUT;
    backlight.pull_up_en = GPIO_PULLUP_DISABLE;
    backlight.pull_down_en = GPIO_PULLDOWN_DISABLE;
    backlight.intr_type = GPIO_INTR_DISABLE;
    if (!check(gpio_config(&backlight), "backlight gpio")) {
        return;
    }
    set_backlight(false);

    spi_bus_config_t buscfg = {};
    buscfg.mosi_io_num = kBox3DisplayMosiPin;
    buscfg.miso_io_num = GPIO_NUM_NC;
    buscfg.sclk_io_num = kBox3DisplaySclkPin;
    buscfg.quadwp_io_num = GPIO_NUM_NC;
    buscfg.quadhd_io_num = GPIO_NUM_NC;
    buscfg.max_transfer_sz = kBox3DisplayWidth * 24 * sizeof(uint16_t);
    esp_err_t err = spi_bus_initialize(SPI3_HOST, &buscfg, SPI_DMA_CH_AUTO);
    if (err != ESP_ERR_INVALID_STATE && !check(err, "spi bus")) {
        return;
    }

    esp_lcd_panel_io_handle_t panel_io = nullptr;
    esp_lcd_panel_io_spi_config_t io_config = {};
    io_config.cs_gpio_num = kBox3DisplayCsPin;
    io_config.dc_gpio_num = kBox3DisplayDcPin;
    io_config.spi_mode = 0;
    io_config.pclk_hz = 40 * 1000 * 1000;
    io_config.trans_queue_depth = 10;
    io_config.lcd_cmd_bits = 8;
    io_config.lcd_param_bits = 8;
    if (!check(esp_lcd_new_panel_io_spi(SPI3_HOST, &io_config, &panel_io), "panel io")) {
        return;
    }

    const ili9341_vendor_config_t vendor_config = {
        .init_cmds = &kVendorInit[0],
        .init_cmds_size = sizeof(kVendorInit) / sizeof(kVendorInit[0]),
    };
    esp_lcd_panel_dev_config_t panel_config = {};
    panel_config.reset_gpio_num = kBox3DisplayResetPin;
    panel_config.flags.reset_active_high = 1;
    panel_config.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB;
    panel_config.bits_per_pixel = 16;
    panel_config.vendor_config = (void*)&vendor_config;
    if (!check(esp_lcd_new_panel_ili9341(panel_io, &panel_config, &panel_), "panel driver")) {
        return;
    }

    if (!check(esp_lcd_panel_reset(panel_), "panel reset") ||
        !check(esp_lcd_panel_init(panel_), "panel init") ||
        !check(esp_lcd_panel_invert_color(panel_, false), "panel invert") ||
        !check(esp_lcd_panel_swap_xy(panel_, false), "panel swap") ||
        !check(esp_lcd_panel_mirror(panel_, true, true), "panel mirror") ||
        !check(esp_lcd_panel_disp_on_off(panel_, true), "panel on")) {
        return;
    }

    ready_ = true;
    mount_assets();
    frame_chunk_ = static_cast<uint16_t*>(heap_caps_malloc(
        kAnimationWidth * kAnimationRowsPerChunk * sizeof(uint16_t),
        MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    if (frame_chunk_ == nullptr) {
        frame_chunk_ = static_cast<uint16_t*>(heap_caps_malloc(
            kAnimationWidth * kAnimationRowsPerChunk * sizeof(uint16_t),
            MALLOC_CAP_8BIT));
    }
    if (frame_chunk_ == nullptr) {
        ESP_LOGW(TAG, "animation buffer allocation failed; using color signals");
    } else {
        xTaskCreate(animation_task, "display_anim", 4096, this, 4, &animation_task_);
    }
    idle();
    ESP_LOGI(TAG, "display ready");
}

void DisplaySignals::idle() {
    if (assets_ready_ && frame_chunk_ != nullptr) {
        start_animation(AnimationState::kWaiting);
    } else {
        fill(kIdleBlue);
    }
    set_backlight(true);
}

void DisplaySignals::listening() {
    if (assets_ready_ && frame_chunk_ != nullptr) {
        start_animation(AnimationState::kListening);
    } else {
        fill(kListenBlue);
        rect(94, 102, 124, 138, kWhite);
        rect(145, 82, 175, 158, kWhite);
        rect(196, 102, 226, 138, kWhite);
    }
    set_backlight(true);
}

void DisplaySignals::recognizing() {
    if (assets_ready_ && frame_chunk_ != nullptr) {
        start_animation(AnimationState::kListening);
    } else {
        fill(kAmber);
    }
    set_backlight(true);
}

void DisplaySignals::success() {
    if (assets_ready_ && frame_chunk_ != nullptr) {
        start_animation(AnimationState::kPlaying);
    } else {
        fill(kGreen);
    }
    set_backlight(true);
}

void DisplaySignals::failure() {
    if (assets_ready_ && frame_chunk_ != nullptr) {
        start_animation(AnimationState::kWaiting);
    } else {
        fill(kRed);
    }
    set_backlight(true);
}

void DisplaySignals::playing() {
    if (assets_ready_ && frame_chunk_ != nullptr) {
        start_animation(AnimationState::kPlaying);
    } else {
        fill(kAmber);
        rect(112, 82, 134, 158, kWhite);
        rect(154, 82, 176, 158, kWhite);
        rect(196, 82, 218, 158, kWhite);
    }
    set_backlight(true);
}

void DisplaySignals::mount_assets() {
    esp_vfs_spiffs_conf_t conf = {};
    conf.base_path = kAssetsBasePath;
    conf.partition_label = "assets";
    conf.max_files = 5;
    conf.format_if_mount_failed = false;
    const esp_err_t err = esp_vfs_spiffs_register(&conf);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "assets mount failed: %s", esp_err_to_name(err));
        return;
    }

    size_t total = 0;
    size_t used = 0;
    if (esp_spiffs_info("assets", &total, &used) == ESP_OK) {
        ESP_LOGI(TAG, "assets mounted total=%u used=%u",
                 static_cast<unsigned>(total), static_cast<unsigned>(used));
    }
    assets_ready_ = true;
}

void DisplaySignals::start_animation(AnimationState state) {
    if (animation_state_ != state) {
        ESP_LOGI(TAG, "display state=%s", animation_name(state));
    }
    animation_state_ = state;
}

void DisplaySignals::stop_animation() {
    animation_state_ = AnimationState::kNone;
}

void DisplaySignals::animation_task(void* arg) {
    static_cast<DisplaySignals*>(arg)->animation_loop();
}

void DisplaySignals::animation_loop() {
    AnimationState previous_state = AnimationState::kNone;
    int frame = 0;
    while (true) {
        const AnimationState state = animation_state_;
        const char* path = animation_path(state);
        if (!ready_ || path == nullptr || frame_chunk_ == nullptr) {
            previous_state = state;
            frame = 0;
            vTaskDelay(pdMS_TO_TICKS(60));
            continue;
        }

        if (state != previous_state) {
            frame = 0;
            previous_state = state;
            ESP_LOGI(TAG, "display animation=%s", path);
        }

        draw_animation_frame(path, frame);
        frame = (frame + 1) % kAnimationFrames;
        vTaskDelay(pdMS_TO_TICKS(kAnimationFrameDelayMs));
    }
}

const char* DisplaySignals::animation_path(AnimationState state) const {
    switch (state) {
        case AnimationState::kWaiting:
            return "/assets/horn-bear/waiting.rgb565";
        case AnimationState::kListening:
            return "/assets/horn-bear/listening.rgb565";
        case AnimationState::kPlaying:
            return "/assets/horn-bear/playing.rgb565";
        case AnimationState::kNone:
        default:
            return nullptr;
    }
}

const char* DisplaySignals::animation_name(AnimationState state) const {
    switch (state) {
        case AnimationState::kWaiting:
            return "waiting";
        case AnimationState::kListening:
            return "listening";
        case AnimationState::kPlaying:
            return "playing";
        case AnimationState::kNone:
        default:
            return "none";
    }
}

void DisplaySignals::draw_animation_frame(const char* path, int frame_index) {
    FILE* file = fopen(path, "rb");
    if (file == nullptr) {
        if (animation_state_ != AnimationState::kNone) {
            ESP_LOGW(TAG, "animation asset missing: %s", path);
            animation_state_ = AnimationState::kNone;
            fill(kIdleBlue);
        }
        return;
    }

    const long frame_bytes = kAnimationWidth * kAnimationHeight * static_cast<long>(sizeof(uint16_t));
    if (fseek(file, frame_bytes * frame_index, SEEK_SET) != 0) {
        fclose(file);
        return;
    }

    if (!lock_draw(500)) {
        fclose(file);
        return;
    }
    for (int y = 0; y < kAnimationHeight; y += kAnimationRowsPerChunk) {
        const int rows = (y + kAnimationRowsPerChunk <= kAnimationHeight)
            ? kAnimationRowsPerChunk
            : (kAnimationHeight - y);
        const size_t expected = kAnimationWidth * rows;
        const size_t read = fread(frame_chunk_, sizeof(uint16_t), expected, file);
        if (read != expected) {
            break;
        }
        draw_centered_square(frame_chunk_, y, rows);
    }
    unlock_draw();
    fclose(file);
}

void DisplaySignals::draw_centered_square(const uint16_t* pixels, int y, int rows) {
    esp_lcd_panel_draw_bitmap(panel_, 0, y, kAnimationWidth, y + rows, pixels);
}

void DisplaySignals::set_backlight(bool on) {
    gpio_set_level(kBox3DisplayBacklightPin, on ? 1 : 0);
}

void DisplaySignals::fill(uint16_t color) {
    rect(0, 0, kBox3DisplayWidth, kBox3DisplayHeight, color);
}

void DisplaySignals::rect(int x0, int y0, int x1, int y1, uint16_t color) {
    if (!ready_ || panel_ == nullptr) {
        return;
    }
    if (!lock_draw()) {
        return;
    }
    static uint16_t line[kBox3DisplayWidth * 20];
    const int width = x1 - x0;
    if (width <= 0 || y1 <= y0) {
        unlock_draw();
        return;
    }
    const int chunk_h = 20;
    for (int i = 0; i < width * chunk_h; ++i) {
        line[i] = color;
    }
    for (int y = y0; y < y1; y += chunk_h) {
        const int h = (y + chunk_h <= y1) ? chunk_h : (y1 - y);
        esp_lcd_panel_draw_bitmap(panel_, x0, y, x1, y + h, line);
    }
    unlock_draw();
}

bool DisplaySignals::lock_draw(uint32_t timeout_ms) {
    if (draw_lock_ == nullptr) {
        return true;
    }
    return xSemaphoreTake(draw_lock_, pdMS_TO_TICKS(timeout_ms)) == pdTRUE;
}

void DisplaySignals::unlock_draw() {
    if (draw_lock_ != nullptr) {
        xSemaphoreGive(draw_lock_);
    }
}

}  // namespace bandtoy
