#pragma once

namespace bandtoy {

enum class CharacterRole {
    kLeader,
    kFollower,
};

enum class TrackRole {
    kMelody,
    kHarmony,
};

struct CharacterProfile {
    const char* id;
    const char* display_name;
    const char* instrument;
    CharacterRole character_role;
    TrackRole track_role;
};

#if BANDTOY_ROLE_LEADER
constexpr CharacterProfile kCharacter = {
    .id = "panda-melody-001",
    .display_name = "Panda",
    .instrument = "music-box lead",
    .character_role = CharacterRole::kLeader,
    .track_role = TrackRole::kMelody,
};
#else
constexpr CharacterProfile kCharacter = {
    .id = "fox-harmony-001",
    .display_name = "Fox",
    .instrument = "soft harmony",
    .character_role = CharacterRole::kFollower,
    .track_role = TrackRole::kHarmony,
};
#endif

}  // namespace bandtoy

