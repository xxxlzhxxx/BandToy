#pragma once

#include <stdint.h>

namespace bandtoy {

class LifeSignals {
public:
    void begin();
    void idle();
    void listening();
    void joining(uint32_t duration_ms);
    void playing();
    void off();

private:
    void set(bool on);
};

}  // namespace bandtoy

