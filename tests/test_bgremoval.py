"""AI Background Removal on a real clip of a person: matting, temporal stability, replacement modes, audio sync,
non-destructive source, and preview vs final consistency. Real model, real FFmpeg renders (no mocks).

Needs the sample person clip in media/ (skipped when it is not there) and the ~26 MB MODNet model, which the
app downloads on first use.

Run:  .venv/bin/python -m unittest -v tests.test_bgremoval
"""
from __future__ import annotations

import glob
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="frameflow_bg_"))
os.environ["FRAMEFLOW_DATA_DIR"] = str(TMP / "data")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import config  # noqa: E402
from backend.main import app  # noqa: E402
from backend.services import matting  # noqa: E402
from video_editor.ffmpeg_ops import probe_video  # noqa: E402

PERSON_SRC = next(iter(sorted(glob.glob(str(ROOT / "media" / "*14085856_1920_1080*.mp4")))), None)
BLUE = (30, 144, 255)


def ff(*args):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-500:])


def wait_job(client, job_id, timeout=900):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.25)
    raise TimeoutError(job_id)


def frame_at(video: Path, t: float, size=(480, 270)) -> np.ndarray:
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, f = cap.read()
    cap.release()
    assert ok, f"no frame at {t}s in {video}"
    return cv2.resize(f, size, interpolation=cv2.INTER_AREA)


def lap_var(img: np.ndarray, mask: np.ndarray) -> float:
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(g, cv2.CV_64F)
    return float(lap[mask].var())


def audio_samples(video: Path) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(out, dtype=np.int16).astype(np.float32) / 32768.0


@unittest.skipUnless(PERSON_SRC, "person sample clip (media/*14085856_1920_1080*.mp4) not present")
class BackgroundRemovalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        work = TMP / "src"
        work.mkdir()
        # 3 s of the real clip plus a tone (the sample has no audio) so sync and audio preservation can be checked
        cls.clip = work / "person.mp4"
        ff("-ss", "2", "-t", "3", "-i", PERSON_SRC, "-f", "lavfi", "-t", "3", "-i", "sine=frequency=440:duration=3",
           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-shortest",
           str(cls.clip))
        cls.clip_hash = hashlib.sha256(cls.clip.read_bytes()).hexdigest()
        cls.image = work / "bg.png"
        ff("-f", "lavfi", "-i", "color=c=0xCC2222:s=640x360", "-frames:v", "1", str(cls.image))
        cls.bgvideo = work / "bg.mp4"
        ff("-f", "lavfi", "-t", "2", "-i", "testsrc2=size=640x360:rate=25", "-pix_fmt", "yuv420p", str(cls.bgvideo))
        cls.pid = cls.client.post("/api/projects", json={"name": "BG"}).json()["id"]
        cls.ids = {k: cls.upload(p) for k, p in (("clip", cls.clip), ("image", cls.image), ("video", cls.bgvideo))}
        for _ in range(900):
            if all(m["status"] != "processing" for m in cls.client.get(f"/api/projects/{cls.pid}/media").json()):
                break
            time.sleep(0.25)
        doc = cls.client.get(f"/api/projects/{cls.pid}").json()["doc"]
        doc.update(style="cinematic", aspect="16:9")
        doc["settings"].update(removeSilence=False, captions=False, normalizeAudio=False, musicSource="none")
        job = wait_job(cls.client, cls.client.post(f"/api/projects/{cls.pid}/generate", json={"doc": doc}).json()["id"])
        assert job["status"] == "done", job.get("error")
        cls.edl = job["result"]["edl"]
        # AI Auto Edit may drop low-scoring parts; keep only clips of the person video
        cls.edl["clips"] = [c for c in cls.edl["clips"] if c["mediaId"] == cls.ids["clip"]]
        cls.edl["look"] = "none"          # a colour grade would tint the replacement colours we measure
        cls.edl["transition"] = None

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        shutil.rmtree(TMP, ignore_errors=True)

    @classmethod
    def upload(cls, path: Path) -> str:
        with open(path, "rb") as fh:
            r = cls.client.post(f"/api/projects/{cls.pid}/media", files={"file": (path.name, fh)})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    # helpers ------------------------------------------------------------------------------------
    def doc_with(self, **bg):
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        edl = {**self.edl, "clips": [dict(c) for c in self.edl["clips"]]}
        for c in edl["clips"]:
            c["bgRemoval"] = {"enabled": True, "mode": "color", "color": "#1E90FF", "blur": 50, "bgMediaId": None, **bg}
        doc["edl"] = edl
        return doc

    def render(self, doc) -> Path:
        job = wait_job(self.client, self.client.post(f"/api/projects/{self.pid}/render", json={"doc": doc}).json()["id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        return config.DATA_DIR / job["result"]["render"]["url"].removeprefix("/files/")

    def baseline(self) -> Path:
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        doc["edl"] = self.edl
        return self.render(doc)

    def src_t(self, t: float) -> float:
        """Source-video time shown at output time t (the first clip may not start at 0)."""
        return self.edl["clips"][0]["srcStart"] + t

    def matte_masks(self, t: float):
        mid = self.ids["clip"]
        row = next(m for m in self.client.get(f"/api/projects/{self.pid}/media").json() if m["id"] == mid)
        path = config.DATA_DIR / "projects" / self.pid / "cache" / f"{mid}_matte.mkv"
        a = frame_at(path, self.src_t(t))[:, :, 0].astype(np.float32) / 255.0
        person = cv2.erode((a > 0.9).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
        bg = ~cv2.dilate((a > 0.02).astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
        return a, person, bg, row

    # tests --------------------------------------------------------------------------------------
    def test_01_runtime_and_license_are_reported(self):
        st = self.client.get("/api/system").json()["backgroundRemoval"]
        self.assertTrue(st["ok"], st)
        self.assertIn("Apache", st["license"])

    def test_02_matte_job_finds_the_person_with_progress(self):
        mid = self.ids["clip"]
        r = self.client.post(f"/api/media/{mid}/matte")
        self.assertEqual(r.status_code, 202, r.text)
        seen = []
        end = time.time() + 600
        while time.time() < end:
            j = self.client.get(f"/api/jobs/{r.json()['id']}").json()
            seen.append(round(j["progress"], 2))
            if j["status"] not in ("queued", "running"):
                break
            time.sleep(0.2)
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertGreater(len(set(seen)), 2, "real progress was reported")
        self.assertTrue(self.client.get(f"/api/media/{mid}/matte").json()["ready"])
        a, person, bg, _ = self.matte_masks(1.5)
        coverage = float((a > 0.5).mean())
        self.assertTrue(0.04 < coverage < 0.40, f"person covers {coverage:.2%} of the frame")
        ys, xs = np.where(a > 0.5)
        self.assertTrue(0.45 < xs.mean() / a.shape[1] < 0.85, "the man stands right of centre in this shot")

    def test_03_matte_is_temporally_stable(self):
        mid = self.ids["clip"]
        path = config.DATA_DIR / "projects" / self.pid / "cache" / f"{mid}_matte.mkv"
        cap = cv2.VideoCapture(str(path))
        frames = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            frames.append(f[:, :, 0].astype(np.float32) / 255.0)
        cap.release()
        self.assertGreater(len(frames), 60)
        smooth = np.mean([np.abs(a - b).mean() for a, b in zip(frames, frames[1:])])
        # the same frames through the network with no smoothing
        src = config.DATA_DIR / "projects" / self.pid / "cache" / f"{mid}_proxy.mp4"
        cap = cv2.VideoCapture(str(src))
        raw = []
        for i in range(60):
            ok, f = cap.read()
            if not ok:
                break
            raw.append(cv2.resize(matting.matte_refined(cv2.resize(f, (480, 270)))[0], (480, 270)))
        cap.release()
        raw_diff = np.mean([np.abs(a - b).mean() for a, b in zip(raw, raw[1:])])
        self.assertLess(smooth, raw_diff, f"smoothing must reduce frame-to-frame change ({smooth:.4f} vs {raw_diff:.4f})")
        self.assertLess(smooth, 0.02)

    def test_04_preview_before_applying(self):
        mid = self.ids["clip"]
        before = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        r = self.client.post(f"/api/media/{mid}/bgpreview", json={"t": self.src_t(1.5), "mode": "color", "color": "#1E90FF"})
        self.assertEqual(r.status_code, 200, r.text[:200])
        img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(img.shape[1], 960)
        small = cv2.resize(img, (480, 270), interpolation=cv2.INTER_AREA)
        a, person, bg, _ = self.matte_masks(1.5)
        corner = small[bg].mean(axis=0)
        self.assertTrue(np.allclose(corner, BLUE[::-1], atol=14), f"background replaced by blue, got {corner}")
        # nothing was applied to the project by previewing
        self.assertEqual(self.client.get(f"/api/projects/{self.pid}").json()["doc"], before, "previewing changes nothing")

    def test_05_solid_colour_replacement_in_the_render(self):
        base = self.baseline()
        out = self.render(self.doc_with(mode="color", color="#1E90FF"))
        t = 1.2
        a, person, bg, _ = self.matte_masks(t)
        f, b0 = frame_at(out, t), frame_at(base, t)
        self.assertTrue(np.allclose(f[bg].mean(axis=0), BLUE[::-1], atol=14), "background is the chosen colour")
        self.assertLess(np.abs(f[person].astype(float) - b0[person].astype(float)).mean(), 14, "subject untouched")
        self.assertGreater(np.abs(f[bg].astype(float) - b0[bg].astype(float)).mean(), 40, "background changed")

    def test_06_blur_keeps_subject_sharp(self):
        base = self.baseline()
        out = self.render(self.doc_with(mode="blur", blur=70))
        t = 1.2
        a, person, bg, _ = self.matte_masks(t)
        f, b0 = frame_at(out, t, (960, 540)), frame_at(base, t, (960, 540))
        sz = (960, 540)
        pm = cv2.resize(person.astype(np.uint8), sz, interpolation=cv2.INTER_NEAREST).astype(bool)
        bm = cv2.resize(bg.astype(np.uint8), sz, interpolation=cv2.INTER_NEAREST).astype(bool)
        self.assertLess(lap_var(f, bm), 0.5 * lap_var(b0, bm), "background is blurred")
        self.assertGreater(lap_var(f, pm), 0.7 * lap_var(b0, pm), "subject keeps its detail")

    def test_07_image_and_video_backgrounds(self):
        t = 1.2
        a, person, bg, _ = self.matte_masks(t)
        img = self.render(self.doc_with(mode="image", bgMediaId=self.ids["image"]))
        f = frame_at(img, t)
        self.assertTrue(np.allclose(f[bg].mean(axis=0), (0x22, 0x22, 0xCC), atol=16), f"uploaded image fills the background: {f[bg].mean(axis=0)}")
        vid = self.render(self.doc_with(mode="video", bgMediaId=self.ids["video"]))
        f1, f2 = frame_at(vid, 0.4), frame_at(vid, 1.6)
        self.assertGreater(np.abs(f1[bg].astype(float) - f2[bg].astype(float)).mean(), 8, "the background video moves")
        self.assertFalse(np.allclose(f1[bg].mean(axis=0), BLUE[::-1], atol=14))

    def test_08_audio_is_preserved_and_in_sync(self):
        base, out = self.baseline(), self.render(self.doc_with(mode="color"))
        self.assertAlmostEqual(probe_video(out).duration, probe_video(base).duration, delta=0.15)
        self.assertTrue(probe_video(out).has_audio)
        a, b = audio_samples(base), audio_samples(out)
        n = min(len(a), len(b))
        self.assertGreater(n, 8000 * 2)
        self.assertLess(np.sqrt(np.mean((a[:n] - b[:n]) ** 2)) / (np.sqrt(np.mean(a[:n] ** 2)) + 1e-9), 0.1,
                        "audio samples match the effect-free render, so sync is unchanged")

    def test_09_disabled_effect_changes_nothing_and_source_is_untouched(self):
        base = self.baseline()
        doc = self.doc_with(mode="color")
        for c in doc["edl"]["clips"]:
            c["bgRemoval"]["enabled"] = False
        off = self.render(doc)
        self.assertLess(np.abs(frame_at(off, 1.2).astype(float) - frame_at(base, 1.2).astype(float)).mean(), 2.0)
        media = next(m for m in self.client.get(f"/api/projects/{self.pid}/media").json() if m["id"] == self.ids["clip"])
        stored = next(iter((config.DATA_DIR / "projects" / self.pid / "media").glob(f"{self.ids['clip']}*")))
        self.assertEqual(hashlib.sha256(stored.read_bytes()).hexdigest(), self.clip_hash, "uploaded source is byte-identical")
        self.assertEqual(media["status"], "ready")

    def test_10_preview_matches_the_final_export(self):
        t = 1.2
        mid = self.ids["clip"]
        r = self.client.post(f"/api/media/{mid}/bgpreview", json={"t": self.src_t(t), "mode": "color", "color": "#1E90FF"})
        prev = cv2.resize(cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR), (480, 270), interpolation=cv2.INTER_AREA)
        doc = self.doc_with(mode="color", color="#1E90FF")
        doc["export"] = {"filename": "bg", "resolution": 1080, "fps": 30, "quality": "draft", "subtitleHandling": "none"}
        job = wait_job(self.client, self.client.post(f"/api/projects/{self.pid}/export", json={"doc": doc}).json()["id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        final = frame_at(Path(job["result"]["path"]), t)
        diff = np.abs(prev.astype(float) - final.astype(float)).mean(axis=2)
        print(f"\npreview vs export: mean abs diff {diff.mean():.2f}/255, {float((diff > 60).mean()):.2%} of pixels differ strongly")
        self.assertLess(diff.mean(), 12.0)
        self.assertLess(float((diff > 60).mean()), 0.08)

    def test_11_clear_errors(self):
        bad = self.render_error(self.doc_with(mode="image", bgMediaId=None))
        self.assertIn("Choose an uploaded image", bad)
        wrong = self.render_error(self.doc_with(mode="image", bgMediaId=self.ids["video"]))
        self.assertIn("is not an image", wrong)
        r = self.client.post(f"/api/media/{self.ids['image']}/matte")
        self.assertEqual(r.status_code, 400)
        self.assertIn("videos", r.json()["detail"])
        r = self.client.post(f"/api/media/{self.ids['clip']}/bgpreview", json={"t": 1.0, "mode": "video", "bgMediaId": None})
        self.assertEqual(r.status_code, 400)

    def render_error(self, doc) -> str:
        job = wait_job(self.client, self.client.post(f"/api/projects/{self.pid}/render", json={"doc": doc}).json()["id"])
        self.assertEqual(job["status"], "failed")
        return job["error"]


if __name__ == "__main__":
    unittest.main()
