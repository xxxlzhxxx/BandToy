import base64
import importlib.util
import json
import os
import sys
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chat_ai import ChatAi, LlmChatClient, VolcTtsClient, synthesize_fallback_wav

SERVER_PATH = Path(__file__).resolve().parent / "server.py"
SPEC = importlib.util.spec_from_file_location("bandtoy_server_chat", SERVER_PATH)
assert SPEC is not None and SPEC.loader is not None
bandtoy_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bandtoy_server)
Handler = bandtoy_server.Handler
QuietThreadingHTTPServer = bandtoy_server.QuietThreadingHTTPServer


DIRECT_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ChatAiTest(unittest.TestCase):
    def test_tts_v3_posts_resource_id_and_parses_chunked_audio(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"code":0,"data":"AQI="}\n{"code":20000000}\n'

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse()

        with patch.dict(os.environ, {
            "VOLC_TTS_APP_ID": "app-id",
            "VOLC_TTS_ACCESS_TOKEN": "access-token",
            "VOLC_TTS_RESOURCE_ID": "seed-tts-2.0",
            "VOLC_TTS_SPEAKER": "zh_female_vv_uranus_bigtts",
        }, clear=True), patch("urllib.request.urlopen", fake_urlopen):
            result = VolcTtsClient().synthesize("你好")

        self.assertEqual(captured["url"], "https://openspeech.bytedance.com/api/v3/tts/unidirectional")
        self.assertEqual(captured["headers"]["X-api-app-id"], "app-id")
        self.assertEqual(captured["headers"]["X-api-access-key"], "access-token")
        self.assertEqual(captured["headers"]["X-api-resource-id"], "seed-tts-2.0")
        self.assertEqual(captured["body"]["req_params"]["text"], "你好")
        self.assertEqual(captured["body"]["req_params"]["speaker"], "zh_female_vv_uranus_bigtts")
        self.assertEqual(captured["body"]["req_params"]["audio_params"]["format"], "pcm")
        self.assertEqual(result.audio, b"\x01\x02")
        self.assertEqual(result.audio_format, "pcm")
        self.assertEqual(result.source, "volc_tts_v3")

    def test_llm_chat_falls_back_without_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            result = LlmChatClient().reply("你好")

        self.assertIn("我听见", result.text)
        self.assertEqual(result.source, "fallback")

    def test_tts_falls_back_to_wav_without_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            result = VolcTtsClient().synthesize("你好")

        self.assertEqual(result.mime_type, "audio/wav")
        self.assertEqual(result.audio[:4], b"RIFF")
        self.assertEqual(result.source, "fallback")

    def test_chat_ai_returns_reply_and_audio(self):
        with patch.dict(os.environ, {}, clear=True):
            response = ChatAi().reply_text("今天有点累")

        self.assertTrue(response.recognized)
        self.assertGreater(len(response.audio), 44)
        self.assertEqual(response.audio_mime_type, "audio/wav")
        self.assertIn("今天有点累", response.spoken_text)

    def test_fallback_wav_uses_24khz_mono_pcm(self):
        wav = synthesize_fallback_wav("test")

        self.assertEqual(wav[:4], b"RIFF")
        self.assertIn(b"WAVEfmt ", wav[:24])
        sample_rate = int.from_bytes(wav[24:28], "little")
        channels = int.from_bytes(wav[22:24], "little")
        bits = int.from_bytes(wav[34:36], "little")
        self.assertEqual(sample_rate, 24000)
        self.assertEqual(channels, 1)
        self.assertEqual(bits, 16)


class ChatServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = QuietThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request_json(self, path, payload=None, headers=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", **(headers or {})},
            method="GET" if payload is None else "POST",
        )
        with DIRECT_HTTP.open(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def get_bytes(self, path):
        with DIRECT_HTTP.open(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            return response.status, response.headers.get("Content-Type"), response.read()

    def test_recognize_chat_mode_returns_tts_url(self):
        with patch.dict(os.environ, {}, clear=True):
            status, body = self.request_json(
                "/recognize?mode=chat",
                {},
                headers={
                    "X-BandToy-Text-Base64": base64.b64encode("你好小熊".encode("utf-8")).decode("ascii"),
                },
            )

        self.assertEqual(status, 200)
        self.assertTrue(body["recognized"])
        self.assertEqual(body["mode"], "voice_chat")
        self.assertIn("spoken_text", body)
        self.assertTrue(body["tts_audio_url"].startswith("http://"))
        self.assertEqual(body["tts_audio_format"], "wav")

        audio_path = "/" + body["tts_audio_url"].split("/", 3)[3]
        audio_status, content_type, audio = self.get_bytes(audio_path)
        self.assertEqual(audio_status, 200)
        self.assertEqual(content_type, "audio/wav")
        self.assertEqual(audio[:4], b"RIFF")


if __name__ == "__main__":
    unittest.main()
