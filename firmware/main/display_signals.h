#pragma once

#include "esp_lcd_panel_ops.h"

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
    void set_backlight(bool on);
    void fill(uint16_t color);
    void rect(int x0, int y0, int x1, int y1, uint16_t color);

    bool ready_ = false;
    esp_lcd_panel_handle_t panel_ = nullptr;
};

}  // namespace bandtoy
