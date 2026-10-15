"""End-to-end tests for the FrameFlow API: real uploads, analysis, renders and exports (no mocks).

Run:  .venv/bin/python -m unittest -v tests.test_frameflow
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="frameflow_test_"))
os.environ["FRAMEFLOW_DATA_DIR"] = str(TMP / "data")

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.services import layout as lay  # noqa: E402
from tests import fixtures  # noqa: E402
from video_editor.ffmpeg_ops import probe_video  # noqa: E402

FIX = fixtures.make(TMP / "fixtures")
SPEECH = ROOT / "sample_videos" / "speech_real.mp4"


def wait(client, job_id, timeout=600):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.25)
    raise TimeoutError(job_id)


class FrameFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.pid = cls.client.post("/api/projects", json={"name": "Test"}).json()["id"]
        cls.ids = {k: cls.upload(cls.pid, FIX[k])["id"] for k in ("multiscene", "portrait", "still", "music")}
        cls.wait_media(cls.pid)

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        shutil.rmtree(TMP, ignore_errors=True)

    @classmethod
    def upload(cls, pid, path: Path) -> dict:
        with open(path, "rb") as fh:
            r = cls.client.post(f"/api/projects/{pid}/media", files={"file": (path.name, fh)})
        assert r.status_code == 201, r.text
        return r.json()

    @classmethod
    def wait_media(cls, pid):
        for _ in range(600):
            media = cls.client.get(f"/api/projects/{pid}/media").json()
            if all(m["status"] != "processing" for m in media):
                return media
            time.sleep(0.25)
        raise TimeoutError("media processing")

    def doc(self, **kw) -> dict:
        d = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        settings = kw.pop("settings", {})
        d.update(kw)
        d["settings"].update(settings)
        return d

    def generate(self, doc: dict, pid=None) -> dict:
        r = self.client.post(f"/api/projects/{pid or self.pid}/generate", json={"doc": doc})
        self.assertEqual(r.status_code, 202, r.text)
        job = wait(self.client, r.json()["id"])
        self.assertEqual(job["status"], "done", job["error"])
        return job

    # ------------------------------------------------------------------ media
    def test_media_metadata_and_assets(self):
        media = {m["id"]: m for m in self.client.get(f"/api/projects/{self.pid}/media").json()}
        v = media[self.ids["multiscene"]]
        self.assertEqual((v["kind"], v["width"], v["height"], v["hasAudio"]), ("video", 1280, 720, True))
        self.assertAlmostEqual(v["duration"], 24.0, delta=0.1)
        for key in ("thumbUrl", "proxyUrl", "spriteUrl", "peaksUrl"):
            r = self.client.get(v["info"][key])
            self.assertEqual(r.status_code, 200, key)
        self.assertFalse(media[self.ids["portrait"]]["hasAudio"])
        self.assertEqual(media[self.ids["still"]]["kind"], "image")
        self.assertEqual(media[self.ids["music"]]["kind"], "audio")
        # range requests (needed for seeking in the browser)
        r = self.client.get(v["info"]["proxyUrl"], headers={"Range": "bytes=0-99"})
        self.assertEqual(r.status_code, 206)

    def test_upload_validation(self):
        r = self.client.post(f"/api/projects/{self.pid}/media", files={"file": ("notes.txt", b"hello")})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Unsupported file type", r.json()["detail"])
        r = self.client.post(f"/api/projects/{self.pid}/media", files={"file": ("fake.mp4", b"not a video at all")})
        self.assertEqual(r.status_code, 400)
        self.assertNotIn(str(TMP), r.json()["detail"])  # no server paths leaked
        r = self.client.post(f"/api/projects/{self.pid}/media", files={"file": ("song.mp3", FIX["still"].read_bytes())})
        self.assertEqual(r.status_code, 400)  # an image renamed .mp3 has no audio stream

    def test_reorder(self):
        ids = [m["id"] for m in self.client.get(f"/api/projects/{self.pid}/media").json()]
        rev = list(reversed(ids))
        out = self.client.put(f"/api/projects/{self.pid}/media/order", json={"ids": rev}).json()
        self.assertEqual([m["id"] for m in out], rev)
        self.client.put(f"/api/projects/{self.pid}/media/order", json={"ids": ids})
        self.assertEqual(self.client.put(f"/api/projects/{self.pid}/media/order", json={"ids": ids[:1]}).status_code, 400)

    # ------------------------------------------------------------------ generation
    def test_styles_formats_and_timeline_accuracy(self):
        results = {}
        for style, aspect, size in (("dynamic", "9:16", (720, 1280)), ("cinematic", "16:9", (1280, 720)),
                                    ("vlog", "1:1", (720, 720))):
            job = self.generate(self.doc(style=style, aspect=aspect, settings={"musicId": None, "removeSilence": style == "vlog"}))
            render, edl = job["result"]["render"], job["result"]["edl"]
            self.assertEqual((render["width"], render["height"]), size, style)
            out = TMP / "data" / render["url"].removeprefix("/files/")
            info = probe_video(out)
            self.assertEqual((info.width, info.height), size)
            planned = lay.layout(edl["clips"], edl["transition"])["duration"]
            self.assertAlmostEqual(info.duration, planned, delta=0.25, msg=f"{style}: render vs timeline")
            results[style] = edl
        durations = {k: [c["srcEnd"] - c["srcStart"] for c in e["clips"]] for k, e in results.items()}
        avg = {k: sum(v) / len(v) for k, v in durations.items()}
        self.assertLess(avg["dynamic"], avg["cinematic"], "dynamic should cut faster than cinematic")
        self.assertEqual(results["dynamic"]["transition"]["type"], "fadewhite")
        self.assertEqual(results["cinematic"]["transition"]["type"], "fade")
        self.assertEqual({e["look"] for e in results.values()}, {"vivid", "cinematic", "warm"})
        # dynamic opens on its best moment
        dyn = results["dynamic"]["clips"]
        self.assertEqual(dyn[0]["score"], max(c["score"] for c in dyn))

    def test_target_duration_and_beat_sync(self):
        job = self.generate(self.doc(style="dynamic", aspect="16:9",
                                     settings={"musicId": self.ids["music"], "beatSync": True, "targetDuration": 12}))
        edl = job["result"]["edl"]
        self.assertTrue(any("beat" in n.lower() for n in edl["notes"]), edl["notes"])
        self.assertAlmostEqual(edl["beat"], 0.5, delta=0.02)  # fixture is a 120 BPM click track
        lt = lay.layout(edl["clips"], edl["transition"])
        self.assertLessEqual(lt["duration"], 12.3)
        d = lt["transition"]
        for c in lt["clips"][1:]:  # every transition midpoint lands on the beat grid
            mid = c["outStart"] + d / 2
            self.assertAlmostEqual((mid / 0.5) - round(mid / 0.5), 0, delta=0.12, msg=mid)
        self.assertEqual(edl["music"]["mediaId"], self.ids["music"])

    def test_rerender_after_timeline_edit_and_export(self):
        job = self.generate(self.doc(style="cinematic", aspect="16:9", settings={"musicId": None}))
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        clips = doc["edl"]["clips"]
        # user edits: drop a clip, trim another, reverse the order
        clips = list(reversed(clips[1:]))
        clips[0]["srcEnd"] = round(clips[0]["srcEnd"] - 0.5, 3)
        doc["edl"]["clips"] = clips
        r = self.client.post(f"/api/projects/{self.pid}/render", json={"doc": doc})
        job = wait(self.client, r.json()["id"])
        self.assertEqual(job["status"], "done", job["error"])
        planned = lay.layout(clips, doc["edl"]["transition"])["duration"]
        self.assertAlmostEqual(job["result"]["render"]["duration"], planned, delta=0.25)

        doc["export"] = {"filename": "My Export!", "resolution": 1080, "fps": 25, "quality": "draft"}
        r = self.client.post(f"/api/projects/{self.pid}/export", json={"doc": doc})
        job = wait(self.client, r.json()["id"])
        self.assertEqual(job["status"], "done", job["error"])
        res = job["result"]
        info = probe_video(Path(res["path"]))
        self.assertEqual((info.width, info.height, round(info.fps)), (1920, 1080, 25))
        self.assertEqual(Path(res["path"]).name, "My Export.mp4")
        self.assertTrue(Path(res["path"]).with_suffix(".frameflow.json").exists())
        dl = self.client.get(f"/api/jobs/{job['id']}/download")
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(len(dl.content), res["size"])

    def test_cancel_and_retry(self):
        doc = self.doc(style="dynamic", aspect="9:16", settings={"musicId": None})
        doc["export"] = {"filename": "cancel-me", "resolution": 1080, "fps": 60, "quality": "high"}
        self.generate(doc)
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        job = self.client.post(f"/api/projects/{self.pid}/export", json={"doc": doc}).json()
        for _ in range(200):
            if self.client.get(f"/api/jobs/{job['id']}").json()["status"] == "running":
                break
            time.sleep(0.05)
        self.client.post(f"/api/jobs/{job['id']}/cancel")
        self.assertEqual(wait(self.client, job["id"])["status"], "cancelled")
        retried = wait(self.client, self.client.post(f"/api/jobs/{job['id']}/retry").json()["id"])
        self.assertEqual(retried["status"], "done", retried["error"])

    def test_errors_are_reported(self):
        empty = self.client.post("/api/projects", json={"name": "Empty"}).json()
        job = self.client.post(f"/api/projects/{empty['id']}/generate", json={"doc": empty["doc"]}).json()
        job = wait(self.client, job["id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("Upload at least one video", job["error"])
        doc = self.doc(settings={"musicId": "doesnotexist"})
        job = wait(self.client, self.client.post(f"/api/projects/{self.pid}/generate", json={"doc": doc}).json()["id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("music", job["error"].lower())
        self.client.delete(f"/api/projects/{empty['id']}")

    # ------------------------------------------------------------------ captions + persistence
    def test_captions_from_real_speech_and_persistence(self):
        pid = self.client.post("/api/projects", json={"name": "Speech"}).json()["id"]
        self.upload(pid, SPEECH)
        self.wait_media(pid)
        doc = self.client.get(f"/api/projects/{pid}").json()["doc"]
        doc.update(style="vlog", aspect="16:9")
        doc["settings"].update(captions=True, removeSilence=True)
        job = self.generate(doc, pid)
        edl = job["result"]["edl"]
        texts = " ".join(c["text"] for c in edl["captions"]).lower()
        for phrase in ("welcome", "pause", "thanks"):
            self.assertIn(phrase, texts)
        spans = lay.caption_spans(edl["captions"], edl["clips"], lay.layout(edl["clips"], edl["transition"])["clips"])
        self.assertEqual(len(spans), 3, "every spoken sentence is kept and captioned")
        self.assertLess(lay.layout(edl["clips"], edl["transition"])["duration"], 7.0, "pauses removed")

        # reopen: EDL, captions and render come back from the database
        p = self.client.get(f"/api/projects/{pid}").json()
        self.assertEqual(len(p["doc"]["edl"]["captions"]), len(edl["captions"]))
        self.assertTrue(p["render"]["url"])
        folder = TMP / "data" / "projects" / pid
        self.assertTrue(folder.exists())
        self.assertEqual(self.client.delete(f"/api/projects/{pid}").status_code, 204)
        self.assertFalse(folder.exists())
        self.assertEqual(self.client.get(f"/api/projects/{pid}").status_code, 404)

    def test_layout_parity_fixture(self):
        """Write a fixture that frontend/src/lib/layout.test.ts checks against the same expectations."""
        clips = [
            {"id": "a", "mediaId": "m1", "srcStart": 0, "srcEnd": 3, "sceneBreak": True},
            {"id": "b", "mediaId": "m1", "srcStart": 3, "srcEnd": 4.5, "sceneBreak": False},
            {"id": "c", "mediaId": "m2", "srcStart": 1, "srcEnd": 2, "sceneBreak": True},
            {"id": "d", "mediaId": "m2", "srcStart": 5, "srcEnd": 9, "sceneBreak": True},
        ]
        transition = {"type": "fade", "duration": 0.8}
        out = lay.layout(clips, transition)
        fixture = ROOT / "frontend" / "src" / "lib" / "layout.fixture.json"
        fixture.write_text(json.dumps({"clips": clips, "transition": transition, "expected": out}, indent=1))
        self.assertEqual(out["transition"], 0.45)  # shrunk to fit the 1 s clip
        self.assertEqual([c["outStart"] for c in out["clips"]], [0, 3, 4.05, 4.6])


if __name__ == "__main__":
    unittest.main()
