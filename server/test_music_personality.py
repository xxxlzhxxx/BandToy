import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from music_personality import CharacterMusicEngine, Emotion, EmotionRouter, build_personality_response


class MusicPersonalityTest(unittest.TestCase):
    def test_router_maps_known_inputs(self):
        router = EmotionRouter()

        self.assertEqual(router.parse_input("happy"), Emotion.HAPPY)
        self.assertEqual(router.parse_input("我今天有点难过"), Emotion.SAD)
        self.assertEqual(router.parse_input("想睡觉了"), Emotion.SLEEP)
        self.assertEqual(router.parse_input("unknown words"), Emotion.CURIOUS)

    def test_variations_share_musicbox_fox_identity(self):
        engine = CharacterMusicEngine.musicbox_fox()

        happy = engine.generate_variation(Emotion.HAPPY)
        sad = engine.generate_variation(Emotion.SAD)
        sleep = engine.generate_variation(Emotion.SLEEP)

        self.assertEqual(engine.theme.character_id, "musicbox_fox")
        self.assertEqual(engine.theme.instrument, "music_box")
        self.assertEqual([note.note for note in engine.theme.base_motif], ["C5", "E5", "G5", "E5"])
        self.assertEqual([note.note for note in happy], ["C5", "E5", "G5", "C6", "G5"])
        self.assertIn("Eb5", [note.note for note in sad])
        self.assertLess(max(note.velocity for note in sleep), max(note.velocity for note in happy))
        self.assertGreater(sleep[-1].duration_ms, happy[-1].duration_ms)

    def test_personality_response_matches_firmware_payload_shape(self):
        response = build_personality_response(Emotion.COMFORT, source_text="我有点累")

        self.assertTrue(response["recognized"])
        self.assertEqual(response["song_id"], 1)
        self.assertEqual(response["character_id"], "musicbox_fox")
        self.assertEqual(response["emotion"], "comfort")
        self.assertEqual(response["response_phrase_id"], "variation_comfort")
        self.assertEqual(response["response_phrase"]["instrument"], "music_box")
        self.assertGreater(len(response["response_phrase"]["notes"]), 0)
        self.assertIn("source_text", response["debug"])


if __name__ == "__main__":
    unittest.main()
