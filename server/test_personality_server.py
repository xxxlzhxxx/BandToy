import json
import importlib.util
import os
import sys
import threading
import unittest
import urllib.request
import base64
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

SERVER_PATH = Path(__file__).resolve().parent / "server.py"
SPEC = importlib.util.spec_from_file_location("bandtoy_server", SERVER_PATH)
assert SPEC is not None and SPEC.loader is not None
bandtoy_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bandtoy_server)
Handler = bandtoy_server.Handler
QuietThreadingHTTPServer = bandtoy_server.QuietThreadingHTTPServer


DIRECT_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class PersonalityServerTest(unittest.TestCase):
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

    def test_personality_score_lists_musicbox_fox(self):
        status, body = self.request_json("/personality/score")

        self.assertEqual(status, 200)
        self.assertEqual(body["character_id"], "musicbox_fox")
        self.assertIn("happy", body["emotions"])

    def test_emotion_text_route_returns_phrase_payload(self):
        with patch.dict(os.environ, {}, clear=True):
            status, body = self.request_json("/emotion", {"text": "我今天好累"})

        self.assertEqual(status, 200)
        self.assertTrue(body["recognized"])
        self.assertEqual(body["emotion"], "comfort")
        self.assertEqual(body["response_phrase"]["phrase_id"], "variation_comfort")

    def test_recognize_personality_mode_accepts_debug_asr_text(self):
        with patch.dict(os.environ, {"BANDTOY_RECOGNIZE_MODE": "personality"}, clear=True):
            status, body = self.request_json(
                "/recognize?mode=personality",
                {},
                headers={
                    "X-BandToy-Text-Base64": base64.b64encode("我很好奇你在想什么".encode("utf-8")).decode("ascii"),
                },
            )

        self.assertEqual(status, 200)
        self.assertTrue(body["recognized"])
        self.assertEqual(body["emotion"], "curious")
        self.assertEqual(body["response_phrase"]["phrase_id"], "variation_curious")


if __name__ == "__main__":
    unittest.main()
