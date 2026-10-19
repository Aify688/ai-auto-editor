"""Hand edits made on the timeline survive saving/reopening and are what the exported MP4 shows.

Moves a text clip, retimes a caption by hand (the transcript stays), moves an audio clip, saves the project, reloads it
and checks the exported video frame by frame / sample by sample.

Run:  .venv/bin/python -m unittest -v tests.test_timeline_persistence
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="frameflow_tlp_"))
os.environ.setdefault("FRAMEFLOW_DATA_DIR", str(TMP / "data"))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.services import layout as lay  # noqa: E402
from tests.test_text_overlays import changed_centroid  # noqa: E402

SPEECH = ROOT / "sample_videos" / "speech_real.mp4"


class TimelinePersistenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.pid = cls.client.post("/api/projects", json={"name": "TL"}).json()["id"]
        with open(SPEECH, "rb") as fh:
            cls.client.post(f"/api/projects/{cls.pid}/media", files={"file": (SPEECH.name, fh)})
        for _ in range(600):
            if cls.client.get(f"/api/projects/{cls.pid}/media").json()[0]["status"] != "processing":
                break
            time.sleep(0.25)
        doc = cls.client.get(f"/api/projects/{cls.pid}").json()["doc"]
        doc.update(style="vlog", aspect="16:9")
        doc["settings"].update(captions=True, removeSilence=False, musicSource="none", boringRemoval=False)
        j = cls.job("generate", doc)
        assert j["status"] == "done", j.get("error")
        cls.edl = j["result"]["edl"]
        cls.edl["look"] = "none"
        cls.edl["transition"] = None
        cls.work = TMP / "w"
        cls.work.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        shutil.rmtree(TMP, ignore_errors=True)

    @classmethod
    def job(cls, kind, doc):
        r = cls.client.post(f"/api/projects/{cls.pid}/{kind}", json={"doc": doc})
        assert r.status_code == 202, r.text
        while True:
            j = cls.client.get(f"/api/jobs/{r.json()['id']}").json()
            if j["status"] not in ("queued", "running"):
                return j
            time.sleep(0.25)

    def doc(self, edl, **export):
        d = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        d["edl"] = edl
        if export:
            d["export"] = {"filename": "t", "fps": 30, "quality": "draft", "subtitleHandling": "burn", **export}
        return d

    def exported(self, edl) -> Path:
        j = self.job("export", self.doc(edl, resolution=720))
        self.assertEqual(j["status"], "done", j.get("error"))
        return Path(j["result"]["path"])

    def title(self, start, duration=1.5):
        return {"id": "t1", "text": "MOVE ME", "start": start, "duration": duration, "position": "center", "x": 0.5, "y": 0.5,
                "size": 0.14, "rotation": 0, "font": "Arial", "weight": "bold", "color": "#FFFFFF", "opacity": 1.0, "align": "center",
                "strokeColor": "#000000", "strokeWidth": 0.06, "shadow": False, "background": "", "backgroundOpacity": 0.65,
                "animation": "none"}

    def test_01_a_text_clip_moved_on_the_timeline_shows_up_at_its_new_time(self):
        plain = {**self.edl, "titles": [], "captions": []}
        base = self.exported(plain)
        before = self.exported({**plain, "titles": [self.title(0.3)]})
        moved = self.exported({**plain, "titles": [self.title(3.4)]})
        # visible at 0.8 s when it starts at 0.3 s, gone there once moved; the reverse at 3.9 s
        self.assertGreater(changed_centroid(before, base, 0.8, self.work)[2], 500)
        self.assertLess(changed_centroid(moved, base, 0.8, self.work)[2], 150)
        self.assertGreater(changed_centroid(moved, base, 3.9, self.work)[2], 500)
        self.assertLess(changed_centroid(before, base, 3.9, self.work)[2], 150)

    def test_02_manual_caption_timing_is_saved_rendered_and_resettable(self):
        caps = self.edl["captions"]
        self.assertTrue(caps and caps[0]["words"], "needs a transcribed caption")
        c = dict(caps[-1])                                   # "Thanks for watching." near the end of the clip
        orig = (c["srcStart"], c["srcEnd"])
        shift = -4.0                                          # moved much earlier by hand
        moved = {**c, "srcStart": round(orig[0] + shift, 3), "srcEnd": round(orig[1] + shift, 3), "manual": True,
                 "origStart": orig[0], "origEnd": orig[1], "wordShift": shift,
                 "words": [dict(w, start=round(w["start"] + shift, 3), end=round(w["end"] + shift, 3)) for w in c["words"]]}
        edl = {**self.edl, "titles": [], "captions": [moved]}
        self.assertEqual(self.client.put(f"/api/projects/{self.pid}", json={"doc": self.doc(edl)}).status_code, 200)
        back = self.client.get(f"/api/projects/{self.pid}").json()["doc"]["edl"]["captions"][0]
        self.assertTrue(back["manual"])
        self.assertEqual((back["origStart"], back["origEnd"], back["wordShift"]), (orig[0], orig[1], shift))
        self.assertEqual(back["text"], c["text"], "the transcript text is untouched")
        # rendered where the user put it, not where speech recognition found it
        keep = {**self.edl, "titles": [], "captions": [], "burnCaptions": True}
        base = self.exported(keep)
        out = self.exported({**edl, "burnCaptions": True})
        lt = lay.layout(self.edl["clips"], None)
        sp_new = lay.caption_spans([back], self.edl["clips"], lt["clips"])
        sp_old = lay.caption_spans([{**back, "srcStart": orig[0], "srcEnd": orig[1]}], self.edl["clips"], lt["clips"])
        self.assertTrue(sp_new and sp_old)
        t_new = (sp_new[0]["outStart"] + sp_new[0]["outEnd"]) / 2
        t_old = (sp_old[0]["outStart"] + sp_old[0]["outEnd"]) / 2
        self.assertGreater(changed_centroid(out, base, t_new, self.work)[2], 400, "caption visible at its manual time")
        if abs(t_new - t_old) > 1.2:
            self.assertLess(changed_centroid(out, base, t_old, self.work)[2], 150, "and not at the transcript time")

    def test_03_everything_together_survives_reopen_and_exports(self):
        edl = {**self.edl, "titles": [self.title(1.0, 2.0)], "markers": [1.0, 3.0],
               "audioClips": [{"id": "x1", "mediaId": "lib:happy", "kind": "music", "start": 1.5, "trimIn": 4.0, "duration": 3.0, "volume": 0.4,
                               "fadeIn": 0.5, "fadeOut": 0.5, "loop": False, "duck": False}]}
        self.assertEqual(self.client.put(f"/api/projects/{self.pid}", json={"doc": self.doc(edl)}).status_code, 200)
        back = self.client.get(f"/api/projects/{self.pid}").json()["doc"]["edl"]
        self.assertEqual(back["markers"], [1.0, 3.0])
        self.assertEqual((back["titles"][0]["start"], back["titles"][0]["duration"]), (1.0, 2.0))
        self.assertEqual((back["audioClips"][0]["start"], back["audioClips"][0]["trimIn"], back["audioClips"][0]["duration"]), (1.5, 4.0, 3.0))
        j = self.job("export", self.doc(back, resolution=720))
        self.assertEqual(j["status"], "done", j.get("error"))
        expected = lay.layout(back["clips"], back["transition"])["duration"]
        from video_editor.ffmpeg_ops import probe_video
        self.assertAlmostEqual(probe_video(Path(j["result"]["path"])).duration, expected, delta=0.4)
        self.assertTrue(probe_video(Path(j["result"]["path"])).has_audio)


if __name__ == "__main__":
    unittest.main()
