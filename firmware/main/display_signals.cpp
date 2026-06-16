#include "display_signals.h"

#include <string.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_lcd_ili9341.h"
#include "esp_lcd_panel_io.h"
#include "esp_log.h"
#include "pins.h"

namespace bandtoy {

namespace {
constexpr const char* TAG = "display_signals";
constexpr uint16_t kBlack = 0x0000;
constexpr uint16_t kIdleBlue = 0x0212;
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
    idle();
    ESP_LOGI(TAG, "display ready");
}

void DisplaySignals::idle() {
    fill(kIdleBlue);
    set_backlight(true);
}

void DisplaySignals::listening() {
    fill(kListenBlue);
    rect(94, 102, 124, 138, kWhite);
    rect(145, 82, 175, 158, kWhite);
    rect(196, 102, 226, 138, kWhite);
    set_backlight(true);
}

void DisplaySignals::recognizing() {
    fill(kAmber);
    rect(82, 108, 238, 132, kWhite);
    set_backlight(true);
}

void DisplaySignals::success() {
    fill(kGreen);
    rect(84, 118, 134, 150, kWhite);
    rect(124, 92, 236, 122, kWhite);
    set_backlight(true);
}

void DisplaySignals::failure() {
    fill(kRed);
    rect(92, 100, 228, 132, kWhite);
    set_backlight(true);
}

void DisplaySignals::playing() {
    fill(kAmber);
    rect(112, 82, 134, 158, kWhite);
    rect(154, 82, 176, 158, kWhite);
    rect(196, 82, 218, 158, kWhite);
    set_backlight(true);
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
    static uint16_t line[kBox3DisplayWidth * 20];
    const int width = x1 - x0;
    if (width <= 0 || y1 <= y0) {
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
}

}  // namespace bandtoy
