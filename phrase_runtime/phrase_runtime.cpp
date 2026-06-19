#include "phrase_runtime.h"

#include <algorithm>
#include <utility>

namespace bandtoy::phrase {

namespace {

std::string actorForInstrument(const std::string& instrument) {
    if (instrument == "music_box") {
        return "A";
    }
    if (instrument == "violin") {
        return "B";
    }
    return "?";
}

}  // namespace

PhrasePlayer::PhrasePlayer(std::string actor_name, std::ostream& out)
    : actor_name_(std::move(actor_name)), out_(&out) {}

void PhrasePlayer::setActorName(std::string actor_name) {
    actor_name_ = std::move(actor_name);
}

void PhrasePlayer::setFinishedCallback(FinishedCallback callback) {
    finished_callback_ = std::move(callback);
}

void PhrasePlayer::play(const Phrase& phrase) {
    current_phrase_ = &phrase;
    started_at_ms_ = now_ms_;
    note_started_.assign(phrase.notes.size(), false);
    *out_ << "[" << now_ms_ << "ms] " << actor_name_ << " starts " << phrase.phrase_id << "\n";
    emitNoteStarts(now_ms_);
}

void PhrasePlayer::update(uint32_t now_ms) {
    now_ms_ = now_ms;
    if (current_phrase_ == nullptr) {
        return;
    }

    emitNoteStarts(now_ms);

    if (now_ms - started_at_ms_ >= current_phrase_->duration_ms) {
        const std::string finished_phrase_id = current_phrase_->phrase_id;
        *out_ << "[" << now_ms << "ms] " << actor_name_ << " finished " << finished_phrase_id << "\n";
        current_phrase_ = nullptr;
        note_started_.clear();
        if (finished_callback_) {
            finished_callback_(finished_phrase_id);
        }
    }
}

bool PhrasePlayer::isPlaying() const {
    return current_phrase_ != nullptr;
}

void PhrasePlayer::emitNoteStarts(uint32_t now_ms) {
    if (current_phrase_ == nullptr) {
        return;
    }
    const uint32_t phrase_time_ms = now_ms - started_at_ms_;
    for (size_t i = 0; i < current_phrase_->notes.size(); ++i) {
        const NoteEvent& note = current_phrase_->notes[i];
        if (!note_started_[i] && phrase_time_ms >= note.start_ms) {
            note_started_[i] = true;
            *out_ << "[" << now_ms << "ms] " << actor_name_ << " "
                  << current_phrase_->instrument << " note " << note.note
                  << " velocity=" << static_cast<int>(note.velocity) << "\n";
        }
    }
}

void ResponseEngine::addRule(const ResponseRule& rule) {
    rules_[rule.heard_phrase_id] = rule;
}

std::optional<std::string> ResponseEngine::getResponsePhraseId(const std::string& heard_phrase_id) {
    const auto found = rules_.find(heard_phrase_id);
    if (found == rules_.end()) {
        return std::nullopt;
    }
    return found->second.response_phrase_id;
}

std::optional<uint32_t> ResponseEngine::getDelayMs(const std::string& heard_phrase_id) const {
    const auto found = rules_.find(heard_phrase_id);
    if (found == rules_.end()) {
        return std::nullopt;
    }
    return found->second.delay_ms;
}

InteractionRuntime::InteractionRuntime(std::ostream& out)
    : out_(&out), player_a_("A", out), player_b_("B", out) {
    player_a_.setFinishedCallback([this](const std::string& phrase_id) {
        onPhraseFinished(phrase_id);
    });
    player_b_.setFinishedCallback([this](const std::string& phrase_id) {
        onPhraseFinished(phrase_id);
    });
}

void InteractionRuntime::addPhrase(const Phrase& phrase) {
    phrases_[phrase.phrase_id] = phrase;
}

void InteractionRuntime::addRule(const ResponseRule& rule) {
    response_engine_.addRule(rule);
}

void InteractionRuntime::startPhrase(const std::string& phrase_id) {
    scheduled_starts_.push_back({now_ms_, phrase_id});
}

void InteractionRuntime::onPhraseFinished(const std::string& phrase_id) {
    const auto response_phrase_id = response_engine_.getResponsePhraseId(phrase_id);
    const auto delay_ms = response_engine_.getDelayMs(phrase_id);
    if (!response_phrase_id || !delay_ms) {
        return;
    }
    scheduled_starts_.push_back({now_ms_ + *delay_ms, *response_phrase_id});
}

void InteractionRuntime::update(uint32_t now_ms) {
    now_ms_ = now_ms;
    player_a_.update(now_ms);
    player_b_.update(now_ms);

    std::sort(scheduled_starts_.begin(), scheduled_starts_.end(), [](const ScheduledStart& a, const ScheduledStart& b) {
        return a.due_ms < b.due_ms;
    });

    while (!scheduled_starts_.empty() && scheduled_starts_.front().due_ms <= now_ms) {
        const std::string phrase_id = scheduled_starts_.front().phrase_id;
        scheduled_starts_.erase(scheduled_starts_.begin());
        startPhraseNow(phrase_id);
    }
}

bool InteractionRuntime::isActive() const {
    return player_a_.isPlaying() || player_b_.isPlaying() || !scheduled_starts_.empty();
}

PhrasePlayer& InteractionRuntime::playerFor(const Phrase& phrase) {
    if (actorForInstrument(phrase.instrument) == "A") {
        return player_a_;
    }
    return player_b_;
}

const Phrase* InteractionRuntime::findPhrase(const std::string& phrase_id) const {
    const auto found = phrases_.find(phrase_id);
    if (found == phrases_.end()) {
        return nullptr;
    }
    return &found->second;
}

void InteractionRuntime::startPhraseNow(const std::string& phrase_id) {
    const Phrase* phrase = findPhrase(phrase_id);
    if (phrase == nullptr) {
        *out_ << "[" << now_ms_ << "ms] missing phrase " << phrase_id << "\n";
        return;
    }

    PhrasePlayer& player = playerFor(*phrase);
    if (player.isPlaying()) {
        *out_ << "[" << now_ms_ << "ms] " << actorForInstrument(phrase->instrument)
              << " skipped " << phrase_id << " because player is busy\n";
        return;
    }
    player.play(*phrase);
}

}  // namespace bandtoy::phrase
