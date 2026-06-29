import importlib.util
import json
import sys
import threading
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SERVER_PATH = Path(__file__).resolve().parent / "server.py"
SPEC = importlib.util.spec_from_file_location("bandtoy_server", SERVER_PATH)
assert SPEC is not None and SPEC.loader is not None
bandtoy_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bandtoy_server)
Handler = bandtoy_server.Handler
QuietThreadingHTTPServer = bandtoy_server.QuietThreadingHTTPServer

DIRECT_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class LibraryUiTest(unittest.TestCase):
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

    def get_json(self, path: str) -> dict:
        with DIRECT_HTTP.open(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))

    def get_text(self, path: str) -> str:
        with DIRECT_HTTP.open(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers.get("Content-Type", ""))
            return response.read().decode("utf-8")

    def test_library_songs_lists_current_song_chain_library(self):
        body = self.get_json("/library/songs")

        titles = [song["title"] for song in body["songs"]]
        self.assertIn("Twinkle Twinkle Little Star", titles)
        self.assertIn("Salut d'Amour", titles)
        salut = next(song for song in body["songs"] if song["song_id"] == 2)
        self.assertEqual(salut["phrase_count"], 4)
        self.assertEqual(salut["melody_note_count"], len(salut["melody_notes"]))
        self.assertGreater(salut["melody_note_count"], 20)
        self.assertEqual(salut["melody_notes"][0]["note"], "G#4")
        self.assertEqual(salut["phrases"][0]["phrase_id"], "salut_phrase_1")
        self.assertEqual(salut["phrases"][0]["next_phrase_id"], "salut_phrase_2")
        self.assertEqual(salut["phrases"][0]["start_note_index"], 0)
        self.assertEqual(salut["phrases"][0]["end_note_index"], 8)

    def test_library_phrase_detail_includes_response_notes(self):
        body = self.get_json("/library/phrases/salut_phrase_1")

        self.assertEqual(body["phrase_id"], "salut_phrase_1")
        self.assertEqual(body["song_id"], 2)
        self.assertEqual(body["next_phrase_id"], "salut_phrase_2")
        self.assertEqual(body["start_note_index"], 0)
        self.assertEqual(body["end_note_index"], 8)
        self.assertEqual(len(body["melody_slice"]), 8)
        self.assertEqual(body["response_phrase"]["phrase_id"], "salut_phrase_2")
        self.assertGreater(len(body["response_phrase"]["notes"]), 0)

    def test_library_page_serves_management_shell(self):
        html = self.get_text("/library")

        self.assertIn("BandToy Library", html)
        self.assertIn("/library/songs", html)
        self.assertIn("phrase-list", html)
        self.assertIn("melody-timeline", html)
        self.assertIn("playPhrase", html)


if __name__ == "__main__":
    unittest.main()
