#include "life_signals.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "pins.h"

namespace bandtoy {

namespace {
constexpr const char* TAG = "life_signals";
}

void LifeSignals::begin() {
    if constexpr (kStatusLedPin == GPIO_NUM_NC) {
        ESP_LOGI(TAG, "no status led configured on this board");
        idle();
    } else {
        gpio_config_t io_conf = {};
        io_conf.pin_bit_mask = 1ULL << kStatusLedPin;
        io_conf.mode = GPIO_MODE_OUTPUT;
        io_conf.pull_up_en = GPIO_PULLUP_DISABLE;
        io_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
        io_conf.intr_type = GPIO_INTR_DISABLE;
        ESP_ERROR_CHECK(gpio_config(&io_conf));
        idle();
    }
}

void LifeSignals::idle() {
    ESP_LOGI(TAG, "state=idle");
    set(false);
}

void LifeSignals::listening() {
    ESP_LOGI(TAG, "state=listening");
    set(true);
}

void LifeSignals::joining(uint32_t duration_ms) {
    ESP_LOGI(TAG, "state=joining duration_ms=%lu", static_cast<unsigned long>(duration_ms));
    const uint32_t step_ms = 180;
    const uint32_t steps = duration_ms / step_ms;
    for (uint32_t i = 0; i < steps; ++i) {
        set((i % 2) == 0);
        vTaskDelay(pdMS_TO_TICKS(step_ms));
    }
    set(true);
}

void LifeSignals::playing() {
    ESP_LOGI(TAG, "state=playing");
    set(true);
}

void LifeSignals::off() {
    ESP_LOGI(TAG, "state=off");
    set(false);
}

void LifeSignals::set(bool on) {
    if constexpr (kStatusLedPin == GPIO_NUM_NC) {
        return;
    }
    gpio_set_level(kStatusLedPin, on ? 1 : 0);
}

}  // namespace bandtoy
