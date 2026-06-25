import gzip
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from emotion_ai import (
    AsrClient,
    EmotionAi,
    LlmEmotionClient,
    VolcAsrProtocol,
    parse_llm_emotion,
)
from music_personality import Emotion


class EmotionAiTest(unittest.TestCase):
    def test_parse_llm_emotion_accepts_json_object_in_text(self):
        parsed = parse_llm_emotion('好的 {"emotion":"comfort","energy":0.3,"intent":"user_is_tired"}')

        self.assertEqual(parsed.emotion, Emotion.COMFORT)
        self.assertEqual(parsed.energy, 0.3)
        self.assertEqual(parsed.intent, "user_is_tired")

    def test_parse_llm_emotion_falls_back_for_bad_output(self):
        parsed = parse_llm_emotion("我觉得用户很开心")

        self.assertEqual(parsed.emotion, Emotion.HAPPY)
        self.assertEqual(parsed.source, "fallback")

    def test_llm_client_falls_back_without_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            client = LlmEmotionClient()
            result = client.classify("我今天有点累")

        self.assertEqual(result.emotion, Emotion.COMFORT)
        self.assertEqual(result.source, "fallback")

    def test_asr_client_reports_missing_credentials(self):
        with patch.dict(os.environ, {
            "VOLC_ASR_APP_ID": "app",
            "VOLC_ASR_SECRET_KEY": "secret",
        }, clear=True):
            result = AsrClient().transcribe(b"abc", "audio/wav")

        self.assertFalse(result.ok)
        self.assertEqual(result.text, "")
        self.assertIn("VOLC_ASR_ACCESS_TOKEN", result.error)

    def test_asr_protocol_builds_full_client_request_frame(self):
        frame = VolcAsrProtocol.build_full_client_request(
            audio_format="wav",
            language="zh-CN",
            uid="test-device",
        )

        self.assertEqual(frame[:4], bytes([0x11, 0x10, 0x11, 0x00]))
        payload_size = int.from_bytes(frame[4:8], "big")
        payload = json.loads(gzip.decompress(frame[8:8 + payload_size]).decode("utf-8"))
        self.assertEqual(payload["audio"]["format"], "wav")
        self.assertEqual(payload["audio"]["rate"], 16000)
        self.assertEqual(payload["audio"]["language"], "zh-CN")
        self.assertEqual(payload["request"]["model_name"], "bigmodel")
        self.assertTrue(payload["request"]["show_utterances"])

    def test_asr_protocol_builds_final_audio_frame(self):
        frame = VolcAsrProtocol.build_audio_request(b"pcm", is_last=True)

        self.assertEqual(frame[:4], bytes([0x11, 0x22, 0x01, 0x00]))
        payload_size = int.from_bytes(frame[4:8], "big")
        self.assertEqual(gzip.decompress(frame[8:8 + payload_size]), b"pcm")

    def test_asr_client_defaults_to_volc_nostream_endpoint_and_resource(self):
        with patch.dict(os.environ, {
            "VOLC_ASR_APP_ID": "app",
            "VOLC_ASR_ACCESS_TOKEN": "token",
        }, clear=True):
            client = AsrClient()

        self.assertEqual(client.url, "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream")
        self.assertEqual(client.resource_id, "volc.seedasr.sauc.duration")

    def test_emotion_ai_text_path_uses_llm_result(self):
        ai = EmotionAi(llm_client=LlmEmotionClient(disabled=True))
        result = ai.classify_text("好开心")

        self.assertEqual(result.emotion, Emotion.HAPPY)
        self.assertEqual(result.text, "好开心")


if __name__ == "__main__":
    unittest.main()
