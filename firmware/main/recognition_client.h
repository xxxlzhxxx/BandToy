#pragma once

#include <stdint.h>

namespace bandtoy {

struct RecognitionResult {
    bool recognized;
    uint16_t song_id;
    float confidence;
    uint32_t position_ms;
    uint32_t position_at_record_end_ms;
    uint32_t join_after_ms;
};

class RecognitionClient {
public:
    void begin();
    RecognitionResult recognize(const int16_t* samples, int sample_count, uint32_t sample_rate);

private:
    bool wifi_ready_ = false;
};

}  // namespace bandtoy
