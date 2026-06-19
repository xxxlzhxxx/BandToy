#pragma once

#include <cstdint>
#include <functional>
#include <iostream>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace bandtoy::phrase {

struct NoteEvent {
    std::string note;
    uint32_t start_ms;
    uint32_t duration_ms;
    uint8_t velocity;
};

struct Phrase {
    std::string phrase_id;
    std::string instrument;
    std::vector<NoteEvent> notes;
    uint32_t duration_ms;
};

struct ResponseRule {
    std::string heard_phrase_id;
    std::string response_phrase_id;
    uint32_t delay_ms;
};

class PhrasePlayer {
public:
    using FinishedCallback = std::function<void(const std::string&)>;

    explicit PhrasePlayer(std::string actor_name = "", std::ostream& out = std::cout);

    void setActorName(std::string actor_name);
    void setFinishedCallback(FinishedCallback callback);
    void play(const Phrase& phrase);
    void update(uint32_t now_ms);
    bool isPlaying() const;

private:
    void emitNoteStarts(uint32_t now_ms);

    std::string actor_name_;
    std::ostream* out_;
    FinishedCallback finished_callback_;
    const Phrase* current_phrase_ = nullptr;
    uint32_t now_ms_ = 0;
    uint32_t started_at_ms_ = 0;
    std::vector<bool> note_started_;
};

class ResponseEngine {
public:
    void addRule(const ResponseRule& rule);
    std::optional<std::string> getResponsePhraseId(const std::string& heard_phrase_id);
    std::optional<uint32_t> getDelayMs(const std::string& heard_phrase_id) const;

private:
    std::unordered_map<std::string, ResponseRule> rules_;
};

class InteractionRuntime {
public:
    explicit InteractionRuntime(std::ostream& out = std::cout);

    void addPhrase(const Phrase& phrase);
    void addRule(const ResponseRule& rule);
    void startPhrase(const std::string& phrase_id);
    void onPhraseFinished(const std::string& phrase_id);
    void update(uint32_t now_ms);
    bool isActive() const;

private:
    struct ScheduledStart {
        uint32_t due_ms;
        std::string phrase_id;
    };

    PhrasePlayer& playerFor(const Phrase& phrase);
    const Phrase* findPhrase(const std::string& phrase_id) const;
    void startPhraseNow(const std::string& phrase_id);

    std::ostream* out_;
    uint32_t now_ms_ = 0;
    PhrasePlayer player_a_;
    PhrasePlayer player_b_;
    ResponseEngine response_engine_;
    std::unordered_map<std::string, Phrase> phrases_;
    std::vector<ScheduledStart> scheduled_starts_;
};

}  // namespace bandtoy::phrase
