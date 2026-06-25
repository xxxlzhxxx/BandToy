#pragma once

#include <stdint.h>

#include "song_runtime.h"

namespace bandtoy {

struct RecognitionResult {
    bool recognized;
    uint16_t song_id;
    float confidence;
    uint32_t position_ms;
    uint32_t position_at_record_end_ms;
    uint32_t join_after_ms;
    bool has_response;
    char response_phrase_id[32];
    uint32_t response_delay_ms;
    RuntimePhrase response_phrase;
};

class RecognitionClient {
public:
    void begin();
    RecognitionResult recognize(const int16_t* samples, int sample_count, uint32_t sample_rate);
    RecognitionResult recognize(const int16_t* samples,
                                int sample_count,
                                uint32_t sample_rate,
                                const char* mode);

private:
    bool wifi_ready_ = false;
};

}  // namespace bandtoy
