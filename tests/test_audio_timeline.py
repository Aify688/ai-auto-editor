"""Audio timeline: clip start, trim, duration, fades, looping, several clips, persistence and exported audio.

The test song is 10 s long and changes pitch every second (300, 400, ... 1200 Hz), so the exported MP4's audio
shows exactly which part of the source plays where. Real FFmpeg renders, no mocks.

Run:  .venv/bin/python -m unittest -v tests.test_audio_timeline
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="frameflow_audio_"))
os.environ.setdefault("FRAMEFLOW_DATA_DIR", str(TMP / "data"))

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.schemas import Edl  # noqa: E402

SR = 16000
TOTAL = 12.0


def ff(*a):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", *a], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-500:])


def decode(path: Path) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(out, dtype=np.int16).astype(np.float32) / 32768.0


def rms(y, t0, t1):
    seg = y[int(t0 * SR): int(t1 * SR)]
    return float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0


def pitch(y, t, win=0.3):
    a = int(round(t * SR))
    seg = y[a: a + int(win * SR)]
    seg = seg * np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(seg))
    return float(np.argmax(spec) * SR / len(seg))


class AudioTimelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        w = TMP / "src"
        w.mkdir()
        expr = "+".join(f"between(t,{k},{k + 1})*sin(2*PI*{300 + 100 * k}*t)" for k in range(10))
        cls.song = w / "song.wav"
        ff("-f", "lavfi", "-i", f"aevalsrc='0.5*({expr})':s=44100:d=10", str(cls.song))
        cls.video = w / "clip.mp4"
        ff("-f", "lavfi", "-i", f"mandelbrot=size=640x360:rate=25", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
           "-t", str(TOTAL), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(cls.video))
        cls.pid = cls.client.post("/api/projects", json={"name": "Audio"}).json()["id"]
        ids = {}
        for key, p in (("video", cls.video), ("song", cls.song)):
            with open(p, "rb") as fh:
                ids[key] = cls.client.post(f"/api/projects/{cls.pid}/media", files={"file": (p.name, fh)}).json()["id"]
        cls.ids = ids
        for _ in range(600):
            if all(m["status"] != "processing" for m in cls.client.get(f"/api/projects/{cls.pid}/media").json()):
                break
            time.sleep(0.25)
        doc = cls.client.get(f"/api/projects/{cls.pid}").json()["doc"]
        doc.update(style="cinematic", aspect="16:9")
        doc["settings"].update(captions=False, musicSource="none", removeSilence=False, boringRemoval=False,
                               targetDuration=None)
        j = cls.job("generate", doc)
        assert j["status"] == "done", j.get("error")
        cls.edl = j["result"]["edl"]
        cls.edl["clips"] = [dict(c, mediaId=ids["video"], srcStart=0.0, srcEnd=TOTAL, sceneBreak=True) for c in cls.edl["clips"][:1]]
        cls.edl.update(music=None, audioClips=[], transition=None, look="none")
        cls.edl["audio"] = {"normalize": False, "lufs": -14, "clean": False, "fades": False}

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

    def clip(self, **kw):
        c = {"id": "a1", "mediaId": self.ids["song"], "kind": "music", "start": 0, "trimIn": 0, "duration": None, "volume": 1.0,
             "fadeIn": 0, "fadeOut": 0, "loop": False, "duck": False}
        c.update(kw)
        return c

    def export(self, *clips) -> np.ndarray:
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        doc["edl"] = {**self.edl, "audioClips": list(clips)}
        doc["export"] = {"filename": "a", "resolution": 720, "fps": 30, "quality": "draft", "subtitleHandling": "none"}
        j = self.job("export", doc)
        self.assertEqual(j["status"], "done", j.get("error"))
        return decode(Path(j["result"]["path"]))

    def test_01_clip_position_and_trim_in(self):
        y = self.export(self.clip(start=3.0, trimIn=2.0, duration=4.0))
        self.assertLess(rms(y, 0.2, 2.8), 0.01, "silent before the clip starts")
        self.assertGreater(rms(y, 3.2, 6.8), 0.1, "audible while the clip plays")
        self.assertLess(rms(y, 7.3, 11.5), 0.01, "silent after its visible duration")
        # source second 2 (500 Hz) plays at output 3 s, source second 3 (600 Hz) at 4 s
        self.assertAlmostEqual(pitch(y, 3.35), 500, delta=25)
        self.assertAlmostEqual(pitch(y, 4.35), 600, delta=25)
        self.assertAlmostEqual(pitch(y, 6.35), 800, delta=25)

    def test_02_without_loop_the_clip_ends_with_its_source(self):
        y = self.export(self.clip(start=1.0, trimIn=8.0))          # only 2 s of source remain
        self.assertGreater(rms(y, 1.3, 2.7), 0.1)
        self.assertLess(rms(y, 3.4, 11.0), 0.01, "it does not repeat unless looping is on")

    def test_03_looping_repeats_the_trimmed_region(self):
        y = self.export(self.clip(start=0.0, trimIn=8.0, duration=7.0, loop=True))
        self.assertAlmostEqual(pitch(y, 0.35), 1100, delta=40)
        self.assertAlmostEqual(pitch(y, 1.35), 1200, delta=40)
        self.assertAlmostEqual(pitch(y, 2.35), 1100, delta=40, msg="second pass of the 8-10 s region")
        self.assertAlmostEqual(pitch(y, 5.35), 1200, delta=40)
        self.assertLess(rms(y, 7.4, 11.5), 0.01)

    def test_04_fade_in_and_out_and_volume(self):
        y = self.export(self.clip(start=0.0, duration=8.0, fadeIn=2.0, fadeOut=2.0, volume=0.5, loop=True))
        self.assertLess(rms(y, 0.0, 0.3), rms(y, 1.0, 1.3) * 0.5)
        self.assertLess(rms(y, 1.0, 1.3), rms(y, 3.0, 3.3))
        self.assertGreater(rms(y, 3.0, 3.3), rms(y, 7.6, 7.9) * 2)
        self.assertLess(rms(y, 3.0, 3.3), 0.5 * 0.5, "volume 0.5 of a 0.5-amplitude source")

    def test_05_several_clips_are_mixed_at_their_own_positions(self):
        y = self.export(self.clip(id="a1", start=0.0, trimIn=0.0, duration=2.0),
                        self.clip(id="a2", start=6.0, trimIn=5.0, duration=2.0, kind="audio"))
        self.assertAlmostEqual(pitch(y, 0.35), 300, delta=25)
        self.assertLess(rms(y, 2.4, 5.6), 0.01)
        self.assertAlmostEqual(pitch(y, 6.35), 800, delta=25)

    def test_06_clip_beyond_the_video_end_is_cut_not_extended(self):
        y = self.export(self.clip(start=10.0, trimIn=0.0, duration=5.0, loop=True))
        self.assertAlmostEqual(len(y) / SR, TOTAL, delta=0.5)
        self.assertGreater(rms(y, 10.2, 11.8), 0.1)

    def test_07_invalid_trim_is_reported(self):
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        doc["edl"] = {**self.edl, "audioClips": [self.clip(trimIn=11.0)]}
        j = self.job("render", doc)
        self.assertEqual(j["status"], "failed")
        self.assertIn("only", j["error"])

    def test_08_timeline_survives_saving_and_reopening(self):
        clips = [self.clip(id="x1", start=2.5, trimIn=1.25, duration=3.5, volume=0.6, fadeIn=0.5, fadeOut=1.0, loop=True, duck=False)]
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        doc["edl"] = {**self.edl, "audioClips": clips, "markers": [1.5, 4.0]}
        self.assertEqual(self.client.put(f"/api/projects/{self.pid}", json={"doc": doc}).status_code, 200)
        back = self.client.get(f"/api/projects/{self.pid}").json()["doc"]["edl"]
        got = back["audioClips"][0]
        for k, v in clips[0].items():
            self.assertEqual(got[k], v, k)
        self.assertEqual(back["markers"], [1.5, 4.0])
        self.assertEqual(back["music"]["mediaId"], self.ids["song"], "the legacy music mirror follows the first music clip")

    def test_09_older_projects_with_only_music_still_load_and_loop(self):
        e = Edl.model_validate({"music": {"mediaId": "lib:happy", "volume": 0.3, "duck": True}})
        self.assertEqual(len(e.audioClips), 1)
        self.assertTrue(e.audioClips[0].loop)
        y = self.export()  # no clips: video's own (silent) audio only
        self.assertLess(rms(y, 0, 11), 0.01)


if __name__ == "__main__":
    unittest.main()
