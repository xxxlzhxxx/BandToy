#pragma once

#include "esp_lcd_panel_ops.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

namespace bandtoy {

class DisplaySignals {
public:
    void begin();
    void idle();
    void listening();
    void recognizing();
    void success();
    void failure();
    void playing();

private:
    enum class AnimationState : uint8_t {
        kNone = 0,
        kWaiting,
        kListening,
        kPlaying,
    };

    void mount_assets();
    void start_animation(AnimationState state);
    void stop_animation();
    void animation_loop();
    const char* animation_path(AnimationState state) const;
    const char* animation_name(AnimationState state) const;
    void draw_animation_frame(const char* path, int frame_index);
    void draw_centered_square(const uint16_t* pixels, int y, int rows);
    static void animation_task(void* arg);
    void set_backlight(bool on);
    void fill(uint16_t color);
    void rect(int x0, int y0, int x1, int y1, uint16_t color);
    bool lock_draw(uint32_t timeout_ms = 1000);
    void unlock_draw();

    bool ready_ = false;
    bool assets_ready_ = false;
    volatile AnimationState animation_state_ = AnimationState::kNone;
    uint16_t* frame_chunk_ = nullptr;
    TaskHandle_t animation_task_ = nullptr;
    SemaphoreHandle_t draw_lock_ = nullptr;
    esp_lcd_panel_handle_t panel_ = nullptr;
};

}  // namespace bandtoy
