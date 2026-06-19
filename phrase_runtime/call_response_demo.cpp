#include "phrase_runtime.h"

#include <cstdint>
#include <utility>

using bandtoy::phrase::InteractionRuntime;
using bandtoy::phrase::NoteEvent;
using bandtoy::phrase::Phrase;
using bandtoy::phrase::ResponseRule;

namespace {

Phrase phrase(std::string phrase_id,
              std::string instrument,
              uint32_t duration_ms,
              std::vector<NoteEvent> notes) {
    Phrase value;
    value.phrase_id = std::move(phrase_id);
    value.instrument = std::move(instrument);
    value.notes = std::move(notes);
    value.duration_ms = duration_ms;
    return value;
}

}  // namespace

int main() {
    InteractionRuntime runtime;

    runtime.addPhrase(phrase("phrase_1", "music_box", 4200, {
        {"E5", 0, 450, 96},
        {"G5", 700, 450, 92},
        {"A5", 1400, 500, 88},
        {"G5", 2300, 600, 84},
        {"E5", 3400, 500, 76},
    }));

    runtime.addPhrase(phrase("response_1", "violin", 3500, {
        {"B4", 0, 900, 72},
        {"C5", 850, 900, 78},
        {"D5", 1700, 1000, 82},
        {"C5", 2700, 700, 70},
    }));

    runtime.addPhrase(phrase("phrase_2", "music_box", 3600, {
        {"A5", 0, 380, 92},
        {"G5", 550, 420, 88},
        {"E5", 1200, 500, 86},
        {"D5", 2100, 520, 80},
        {"E5", 3000, 420, 76},
    }));

    runtime.addPhrase(phrase("response_2", "violin", 4000, {
        {"G4", 0, 1100, 70},
        {"A4", 1000, 900, 75},
        {"B4", 1900, 900, 80},
        {"E5", 2850, 1000, 78},
    }));

    runtime.addRule({"phrase_1", "response_1", 500});
    runtime.addRule({"response_1", "phrase_2", 600});
    runtime.addRule({"phrase_2", "response_2", 700});

    runtime.startPhrase("phrase_1");

    for (uint32_t now_ms = 0; now_ms <= 20000 && runtime.isActive(); now_ms += 50) {
        runtime.update(now_ms);
    }

    return 0;
}
