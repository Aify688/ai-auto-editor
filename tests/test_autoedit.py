"""Auto-edit extras: filler-word detection feeding the editor's cut list."""
import unittest
from unittest import mock

from backend.services import pipeline


class FillerTest(unittest.TestCase):
    def test_fillers_are_found_and_trimmed(self):
        cues = [{"start": 0, "end": 4, "text": "So um we start", "words": [
            {"word": "So", "start": 0.0, "end": 0.3}, {"word": "um,", "start": 0.4, "end": 0.8},
            {"word": "we", "start": 0.9, "end": 1.1}, {"word": "Uh", "start": 2.0, "end": 2.02},   # too short: ignored
            {"word": "嗯", "start": 3.0, "end": 3.4}, {"word": "start", "start": 3.5, "end": 3.9}]}]
        rows = [{"id": "m1", "kind": "video", "has_audio": 1, "name": "a.mp4"}]
        data = {"m1": {"audio": {"silences": []}}}
        ctx = mock.Mock()
        with mock.patch.object(pipeline.system, "status", return_value={"transcription": {"ok": True}}), \
             mock.patch.object(pipeline.analysis, "transcript", return_value={"cues": cues}):
            n = pipeline._mark_fillers(rows, data, ctx, "auto")
        self.assertEqual(n, 2)
        self.assertEqual(data["m1"]["audio"]["fillers"], [[0.44, 0.76], [3.04, 3.36]])

    def test_no_speech_engine_means_no_fillers(self):
        with mock.patch.object(pipeline.system, "status", return_value={"transcription": {"ok": False}}):
            self.assertEqual(pipeline._mark_fillers([], {}, mock.Mock(), "auto"), 0)


if __name__ == "__main__":
    unittest.main()
