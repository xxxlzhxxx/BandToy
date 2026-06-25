import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SERVER_PATH = Path(__file__).resolve().parent / "server.py"
SPEC = importlib.util.spec_from_file_location("bandtoy_server", SERVER_PATH)
assert SPEC is not None and SPEC.loader is not None
bandtoy_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bandtoy_server)


class SongChainTest(unittest.TestCase):
    def test_salut_damour_phrase_1_returns_phrase_2(self):
        observed = [68, 59, 68, 66, 64, 63, 64, 69]
        result = bandtoy_server.match_position(observed, audio_duration_ms=5000)
        result = bandtoy_server.attach_response(result, client_key="test-client")

        self.assertTrue(result["recognized"])
        self.assertEqual(result["song_id"], 2)
        self.assertEqual(result["heard_phrase_id"], "salut_phrase_1")
        self.assertEqual(result["response_phrase_id"], "salut_phrase_2")
        self.assertEqual(result["response_phrase"]["notes"][0]["note"], "A4")


if __name__ == "__main__":
    unittest.main()
