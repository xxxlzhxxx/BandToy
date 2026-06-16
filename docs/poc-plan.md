# PoC Plan

## Milestone 1: One Device Plays a Track

Acceptance:

- Device boots.
- LED breathes while idle.
- Button or auto-start triggers the song.
- Buzzer plays the melody with recognizable timing.

## Milestone 2: Two Devices Discover Each Other

Acceptance:

- Leader broadcasts a play announcement over ESP-NOW.
- Follower logs the received song id and bpm.
- Follower changes LED state when it hears the leader.

## Milestone 3: Follower Joins

Acceptance:

- Leader plays melody.
- Follower waits one bar.
- Follower plays harmony.
- The scene reads as a duet, not as two independent sounds.

## Milestone 4: Tune the Feeling

Acceptance:

- Joining delay feels intentional.
- LED behavior suggests "waking" and "joining".
- The duet remains stable for the length of Twinkle Twinkle Little Star.

## Non-Goals

- No app.
- No large model.
- No microphone.
- No mechanical actuator.
- No commercial packaging.

