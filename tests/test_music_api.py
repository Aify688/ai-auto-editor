"""Recommended Music: the endpoint always speaks JSON (never the web page), errors are readable, the licensed library can be
previewed, and applying a track puts it on the audio timeline and into the exported MP4 (volume and ducking included).

Run:  .venv/bin/python -m unittest -v tests.test_music_api
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="frameflow_music_"))
os.environ.setdefault("FRAMEFLOW_DATA_DIR", str(TMP / "data"))

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.services import system as system_svc  # noqa: E402

SPEECH = ROOT / "sample_videos" / "speech_real.mp4"
SR = 16000


def decode(p: Path) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(out, dtype=np.int16).astype(np.float32) / 32768.0


def rms(y, a, b):
    seg = y[int(a * SR): int(b * SR)]
    return float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0


class MusicApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.empty = cls.client.post("/api/projects", json={"name": "Empty"}).json()["id"]
        cls.pid = cls.client.post("/api/projects", json={"name": "Music"}).json()["id"]
        with open(SPEECH, "rb") as fh:
            cls.client.post(f"/api/projects/{cls.pid}/media", files={"file": (SPEECH.name, fh)})
        for _ in range(600):
            if cls.client.get(f"/api/projects/{cls.pid}/media").json()[0]["status"] != "processing":
                break
            time.sleep(0.25)

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        shutil.rmtree(TMP, ignore_errors=True)

    def job(self, kind, doc):
        r = self.client.post(f"/api/projects/{self.pid}/{kind}", json={"doc": doc})
        self.assertEqual(r.status_code, 202, r.text)
        while True:
            j = self.client.get(f"/api/jobs/{r.json()['id']}").json()
            if j["status"] not in ("queued", "running"):
                return j
            time.sleep(0.25)

    # 1. routing ----------------------------------------------------------------------------------------
    def test_01_unknown_api_paths_are_json_404_never_the_web_page(self):
        for path in ("/api/projects/abc/does-not-exist", "/api/nothing-here", "/files/projects/nope.mp4", "/api/projects/zzz/music-recommendations"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 404, path)
            self.assertIn("application/json", r.headers["content-type"], path)
            self.assertNotIn("<!doctype", r.text.lower(), path)
        if (ROOT / "frontend" / "dist" / "index.html").exists():
            home = self.client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("text/html", home.headers["content-type"])
            self.assertEqual(self.client.get("/some/client/route").status_code, 200, "SPA routes still get the app")

    def test_02_no_footage_is_a_readable_json_error(self):
        r = self.client.get(f"/api/projects/{self.empty}/music-recommendations")
        self.assertEqual(r.status_code, 409)
        self.assertIn("application/json", r.headers["content-type"])
        self.assertIn("Upload a video", r.json()["detail"])

    # 2. recommendations ----------------------------------------------------------------------------------
    def test_03_before_analysis_recommendations_come_from_the_style_and_say_so(self):
        r = self.client.get(f"/api/projects/{self.pid}/music-recommendations")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("application/json", r.headers["content-type"])
        body = r.json()
        self.assertEqual(body["basis"], "style")
        self.assertEqual(len(body["tracks"]), 3)

    def test_04_after_generation_three_tracks_with_reasons_and_attribution(self):
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        doc.update(style="vlog", aspect="16:9")
        doc["settings"].update(captions=False, musicSource="none", removeSilence=False)
        j = self.job("generate", doc)
        self.assertEqual(j["status"], "done", j.get("error"))
        r = self.client.get(f"/api/projects/{self.pid}/music-recommendations")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["basis"], "footage")
        self.assertEqual(body["license"], "CC BY 4.0")
        self.assertIn("Tanner Helland", body["attribution"])
        self.assertEqual(set(body), {"basis", "style", "profile", "license", "attribution", "tracks"})
        self.assertEqual(len(body["tracks"]), 3)
        keys = {"id", "mood", "title", "duration", "attribution", "url", "tempo", "score", "reason", "suggestedVolume"}
        for t in body["tracks"]:
            self.assertEqual(set(t), keys)
            self.assertTrue(t["id"].startswith("lib:"))
            self.assertGreater(len(t["reason"]), 10)
            self.assertIn("CC BY", t["attribution"])
        self.assertEqual([t["score"] for t in body["tracks"]], sorted((t["score"] for t in body["tracks"]), reverse=True))

    # 3. preview ------------------------------------------------------------------------------------------
    def test_05_every_recommended_track_can_be_previewed(self):
        for t in self.client.get(f"/api/projects/{self.pid}/music-recommendations").json()["tracks"]:
            r = self.client.get(t["url"])
            self.assertEqual(r.status_code, 200, t["url"])
            self.assertIn("audio", r.headers["content-type"])
            self.assertGreater(len(r.content), 50_000)
            part = self.client.get(t["url"], headers={"Range": "bytes=0-1023"})
            self.assertEqual(part.status_code, 206, "seeking in the preview works (HTTP range)")

    # 4. apply -> timeline -> export ----------------------------------------------------------------------
    def test_06_applied_music_lands_on_the_timeline_and_in_the_mp4_with_volume(self):
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        track = self.client.get(f"/api/projects/{self.pid}/music-recommendations").json()["tracks"][0]
        edl = doc["edl"]
        edl["look"] = "none"
        edl["audio"] = {**edl["audio"], "normalize": False, "clean": False, "fades": False}
        clip = lambda **kw: {"id": "a1", "mediaId": track["id"], "kind": "music", "start": 0, "trimIn": 0, "duration": None,  # noqa: E731
                             "volume": 0.35, "fadeIn": 0, "fadeOut": 0, "loop": True, "duck": True, **kw}

        def export(clips, name):
            d = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
            d["edl"] = {**edl, "audioClips": clips, "music": None if not clips else {"mediaId": clips[0]["mediaId"], "volume": clips[0]["volume"], "duck": clips[0]["duck"]}}
            d["export"] = {"filename": name, "resolution": 720, "fps": 30, "quality": "draft", "subtitleHandling": "none"}
            j = self.job("export", d)
            self.assertEqual(j["status"], "done", j.get("error"))
            return decode(Path(j["result"]["path"]))

        # saved project: the applied track is a clip on the editable audio timeline
        saved = {**doc, "edl": {**edl, "audioClips": [clip()]}}
        self.assertEqual(self.client.put(f"/api/projects/{self.pid}", json={"doc": saved}).status_code, 200)
        back = self.client.get(f"/api/projects/{self.pid}").json()["doc"]["edl"]
        self.assertEqual(back["audioClips"][0]["mediaId"], track["id"])
        self.assertEqual(back["music"]["mediaId"], track["id"], "legacy mirror")

        plain = export([], "plain")
        with_music = export([clip(duck=False)], "music")
        ducked = export([clip(duck=True)], "ducked")
        quiet = export([clip(duck=False, volume=0.07)], "quiet")
        n = min(len(plain), len(with_music), len(ducked), len(quiet))
        # in the pause between sentences (no speech) the music is plainly there; without it that part is quiet
        pause = (2.0, 2.5)
        self.assertGreater(rms(with_music[:n], *pause), rms(plain[:n], *pause) + 0.002, "exported MP4 contains the music")
        # volume setting scales it
        self.assertLess(rms(quiet[:n], *pause), rms(with_music[:n], *pause) * 0.4, "lower volume is quieter")

    def test_07_ducking_lowers_the_music_only_while_someone_speaks(self):
        """A 1 kHz tone stands in for speech (2-4 s). Energy at 100-600 Hz is the music."""
        w = TMP / "duck"
        w.mkdir(exist_ok=True)
        src = w / "tone.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "mandelbrot=size=320x180:rate=25", "-f", "lavfi", "-i",
                        "sine=frequency=1000:duration=6,volume='0.5*between(t,2,4)':eval=frame", "-t", "6", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)], check=True)
        pid = self.client.post("/api/projects", json={"name": "Duck"}).json()["id"]
        with open(src, "rb") as fh:
            self.client.post(f"/api/projects/{pid}/media", files={"file": (src.name, fh)})
        for _ in range(600):
            if self.client.get(f"/api/projects/{pid}/media").json()[0]["status"] != "processing":
                break
            time.sleep(0.25)
        doc = self.client.get(f"/api/projects/{pid}").json()["doc"]
        doc.update(style="cinematic")
        doc["settings"].update(captions=False, musicSource="none", removeSilence=False, boringRemoval=False, targetDuration=None)

        def run(kind, d):
            r = self.client.post(f"/api/projects/{pid}/{kind}", json={"doc": d})
            self.assertEqual(r.status_code, 202, r.text)
            while True:
                j = self.client.get(f"/api/jobs/{r.json()['id']}").json()
                if j["status"] not in ("queued", "running"):
                    return j
                time.sleep(0.25)
        g = run("generate", doc)
        self.assertEqual(g["status"], "done", g.get("error"))
        edl = g["result"]["edl"]
        edl.update(look="none", transition=None, music=None)
        edl["audio"] = {**edl["audio"], "normalize": False, "clean": False, "fades": False}

        def band(y, a, b):                       # music energy at 100-600 Hz, far from the 1 kHz "voice" tone
            seg = y[int(a * SR): int(b * SR)] * np.hanning(int((b - a) * SR))
            spec = np.abs(np.fft.rfft(seg)) ** 2
            f = np.fft.rfftfreq(len(seg), 1 / SR)
            return float(spec[(f > 100) & (f < 600)].sum())

        def export(duck):
            clips = [] if duck is None else [{"id": "a1", "mediaId": "lib:energetic", "kind": "music", "start": 0, "trimIn": 20, "duration": None,
                                              "volume": 0.6, "fadeIn": 0, "fadeOut": 0, "loop": True, "duck": duck}]
            d = {**doc, "edl": {**edl, "audioClips": clips, "music": {"mediaId": "lib:energetic", "volume": 0.6, "duck": duck} if clips else None},
                 "export": {"filename": "d", "resolution": 720, "fps": 30, "quality": "draft", "subtitleHandling": "none"}}
            j = run("export", d)
            self.assertEqual(j["status"], "done", j.get("error"))
            return decode(Path(j["result"]["path"]))
        none, free, ducked = export(None), export(False), export(True)

        def music(y, a, b):                      # music energy = this mix minus the same mix without music (removes codec noise)
            return max(0.0, band(y, a, b) - band(none, a, b))
        before = music(ducked, 0.3, 1.5) / music(free, 0.3, 1.5)
        during = music(ducked, 2.4, 3.6) / music(free, 2.4, 3.6)
        self.assertGreater(music(free, 2.4, 3.6), 0, "there was music to duck")
        self.assertGreater(before, 0.8, "music is untouched before anyone speaks")
        self.assertLess(during, 0.35, "music is pushed down while the voice is present")

    # 5. server freshness ----------------------------------------------------------------------------------
    def test_08_a_server_older_than_its_code_is_detected(self):
        self.assertFalse(self.client.get("/api/system").json()["server"]["stale"])
        old = system_svc._BOOT_CODE
        try:
            system_svc._BOOT_CODE = old - 1000
            system_svc._stale_cache = (0.0, False)
            self.assertTrue(self.client.get("/api/system").json()["server"]["stale"])
        finally:
            system_svc._BOOT_CODE = old
            system_svc._stale_cache = (0.0, False)


if __name__ == "__main__":
    unittest.main()
