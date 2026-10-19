"""Editable text overlays: position/size/rotation relative to the frame, fonts, stroke/shadow/background, animation,
and identical placement in preview-resolution renders and full-resolution exports. Real Pillow + FFmpeg output.

Run:  .venv/bin/python -m unittest -v tests.test_text_overlays
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
TMP = Path(tempfile.mkdtemp(prefix="frameflow_text_"))
os.environ.setdefault("FRAMEFLOW_DATA_DIR", str(TMP / "data"))

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from backend import config  # noqa: E402
from backend.main import app  # noqa: E402
from video_editor import skills  # noqa: E402
from video_editor.overlay import available_fonts, text_object_layer  # noqa: E402

SPEECH = ROOT / "sample_videos" / "speech_real.mp4"
SIZE = (800, 450)


def base(**kw):
    s = {"text": "Hello world", "x": 0.5, "y": 0.5, "size": 0.1, "rotation": 0, "font": "Arial", "weight": "bold",
         "color": "#FFFFFF", "opacity": 1.0, "align": "center", "strokeColor": "#000000", "strokeWidth": 0.0,
         "shadow": False, "background": "", "backgroundOpacity": 0.65, "animation": "none", "start": 0, "duration": 3}
    s.update(kw)
    return s


def bbox(img):
    return img.getchannel("A").point(lambda p: 255 if p > 20 else 0).getbbox()


def centre(img):
    b = bbox(img)
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


class TextLayerTest(unittest.TestCase):
    def test_position_is_relative_to_the_frame(self):
        for x, y in ((0.5, 0.5), (0.25, 0.3), (0.8, 0.85)):
            cx, cy = centre(text_object_layer(SIZE, base(x=x, y=y)))
            self.assertAlmostEqual(cx / SIZE[0], x, delta=0.02)
            self.assertAlmostEqual(cy / SIZE[1], y, delta=0.03)

    def test_same_relative_position_at_double_resolution(self):
        a = centre(text_object_layer(SIZE, base(x=0.3, y=0.7)))
        b = centre(text_object_layer((1600, 900), base(x=0.3, y=0.7)))
        self.assertAlmostEqual(a[0] / SIZE[0], b[0] / 1600, delta=0.01)
        self.assertAlmostEqual(a[1] / SIZE[1], b[1] / 900, delta=0.01)

    def test_size_and_rotation(self):
        small, big = bbox(text_object_layer(SIZE, base(size=0.06))), bbox(text_object_layer(SIZE, base(size=0.12)))
        self.assertAlmostEqual((big[3] - big[1]) / (small[3] - small[1]), 2.0, delta=0.35)
        flat, turned = bbox(text_object_layer(SIZE, base())), bbox(text_object_layer(SIZE, base(rotation=90)))
        self.assertGreater(flat[2] - flat[0], flat[3] - flat[1])
        self.assertGreater(turned[3] - turned[1], turned[2] - turned[0], "rotated 90 degrees: taller than wide")

    def test_fonts_weight_and_style_options(self):
        fams = {f["family"] for f in available_fonts()}
        self.assertIn("Arial", fams)
        arial = bbox(text_object_layer(SIZE, base(font="Arial")))
        other = [f for f in ("Georgia", "Courier New", "Impact") if f in fams]
        self.assertTrue(other)
        self.assertNotEqual(arial[2] - arial[0], bbox(text_object_layer(SIZE, base(font=other[0])))[2] - arial[0])
        bold, normal = text_object_layer(SIZE, base(weight="bold")), text_object_layer(SIZE, base(weight="normal"))
        self.assertGreater(np.asarray(bold.getchannel("A")).sum(), np.asarray(normal.getchannel("A")).sum())
        plain = np.asarray(text_object_layer(SIZE, base()).getchannel("A")).sum()
        self.assertGreater(np.asarray(text_object_layer(SIZE, base(strokeWidth=0.12)).getchannel("A")).sum(), plain)
        self.assertGreater(np.asarray(text_object_layer(SIZE, base(shadow=True)).getchannel("A")).sum(), plain)
        self.assertGreater(np.asarray(text_object_layer(SIZE, base(background="#000000")).getchannel("A")).sum(), plain * 2)

    def test_colour_opacity_and_alignment(self):
        red = np.asarray(text_object_layer(SIZE, base(color="#FF0000")).convert("RGBA"))
        opaque = red[red[..., 3] > 250]
        self.assertTrue(len(opaque) and opaque[..., 0].mean() > 240 and opaque[..., 1].mean() < 20)
        half = np.asarray(text_object_layer(SIZE, base(opacity=0.5)).getchannel("A")).max()
        self.assertAlmostEqual(half / 255, 0.5, delta=0.03)
        txt = "Line one is long\nshort"
        left = np.asarray(text_object_layer(SIZE, base(text="A very long first line of text", size=0.09, align="left")).getchannel("A"))
        self.assertTrue(left.sum() > 0)

    def test_animation_frames_and_timing(self):
        ctx = skills.OverlayCtx(SIZE, 10.0, [(0, 0.0, 10.0, 0.0)])
        for kind in ("fade", "pop", "scale", "slide"):
            items = skills.overlay_title(base(animation=kind, start=2, duration=3), ctx)
            self.assertAlmostEqual(min(i.start for i in items), 2.0, places=2)
            self.assertAlmostEqual(max(i.end for i in items), 5.0, places=2)
            starts = next(i for i in items if bbox(i.image) and i.start < 2.3)
            mid = [i for i in items if i.start <= 3.5 < i.end][0]
            self.assertLess(starts.image.getchannel("A").getextrema()[1], mid.image.getchannel("A").getextrema()[1] + 1 if kind != "pop" else 256)
            if kind in ("pop", "scale"):
                self.assertLess(bbox(starts.image)[2] - bbox(starts.image)[0], bbox(mid.image)[2] - bbox(mid.image)[0])
        still = skills.overlay_title(base(animation="none", start=1, duration=2), ctx)
        self.assertEqual(len(still), 1)

    def test_legacy_titles_keep_working(self):
        ctx = skills.OverlayCtx(SIZE, 10.0, [(0, 0.0, 10.0, 0.0)])
        legacy = {"text": "Old title", "start": 0.0, "duration": 2.0, "position": "bottom"}
        items = skills.overlay_title({**legacy, "size": 0.07, "y": None, "x": 0.5, "font": "Arial", "weight": "bold",
                                      "color": "#FFFFFF", "opacity": 1.0, "align": "center", "rotation": 0,
                                      "background": "#000000", "backgroundOpacity": 0.65, "animation": "none"}, ctx)
        self.assertGreater(centre(items[0].image)[1] / SIZE[1], 0.8, "bottom preset sits near the bottom")


def changed_centroid(a: Path, b: Path, t: float, work: Path):
    def grab(p, name):
        out = work / name
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t}", "-i", str(p), "-frames:v", "1", str(out)], check=True)
        return np.asarray(Image.open(out).convert("L"), dtype=np.int16)
    fa, fb = grab(a, "a.png"), grab(b, "b.png")
    mask = np.abs(fa - fb) > 70
    ys, xs = np.where(mask)
    return xs.mean() / fa.shape[1], ys.mean() / fa.shape[0], mask.sum()


class ExportConsistencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.pid = cls.client.post("/api/projects", json={"name": "Text"}).json()["id"]
        with open(SPEECH, "rb") as fh:
            cls.client.post(f"/api/projects/{cls.pid}/media", files={"file": (SPEECH.name, fh)})
        for _ in range(600):
            if cls.client.get(f"/api/projects/{cls.pid}/media").json()[0]["status"] != "processing":
                break
            time.sleep(0.25)
        doc = cls.client.get(f"/api/projects/{cls.pid}").json()["doc"]
        doc.update(style="vlog", aspect="16:9")
        doc["settings"].update(captions=False, musicSource="none", removeSilence=False)
        j = cls.run_job("generate", doc)
        assert j["status"] == "done", j.get("error")
        cls.edl = j["result"]["edl"]
        cls.edl["look"] = "none"
        cls.work = TMP / "w"
        cls.work.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        shutil.rmtree(TMP, ignore_errors=True)

    @classmethod
    def run_job(cls, kind, doc):
        r = cls.client.post(f"/api/projects/{cls.pid}/{kind}", json={"doc": doc})
        assert r.status_code == 202, r.text
        while True:
            j = cls.client.get(f"/api/jobs/{r.json()['id']}").json()
            if j["status"] not in ("queued", "running"):
                return j
            time.sleep(0.25)

    def doc(self, titles, **export):
        d = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        d["edl"] = {**self.edl, "titles": titles, "captions": []}
        if export:
            d["export"] = {"filename": "t", "fps": 30, "quality": "draft", "subtitleHandling": "none", **export}
        return d

    def test_preview_and_export_place_text_at_the_same_relative_spot(self):
        title = {"id": "t1", "text": "MOVED", "start": 0.0, "duration": 3.0, "position": "center", "x": 0.25, "y": 0.3,
                 "size": 0.12, "rotation": 0, "font": "Arial", "weight": "bold", "color": "#FFFFFF", "opacity": 1.0,
                 "align": "center", "strokeColor": "#000000", "strokeWidth": 0.05, "shadow": False, "background": "",
                 "backgroundOpacity": 0.65, "animation": "none"}
        pre = self.run_job("render", self.doc([title]))
        pre0 = self.run_job("render", self.doc([]))
        ex = self.run_job("export", self.doc([title], resolution=1080))
        ex0 = self.run_job("export", self.doc([], resolution=1080))
        for j in (pre, pre0, ex, ex0):
            self.assertEqual(j["status"], "done", j.get("error"))
        p = changed_centroid(config.DATA_DIR / pre["result"]["render"]["url"].removeprefix("/files/"),
                             config.DATA_DIR / pre0["result"]["render"]["url"].removeprefix("/files/"), 1.0, self.work)
        e = changed_centroid(Path(ex["result"]["path"]), Path(ex0["result"]["path"]), 1.0, self.work)
        self.assertGreater(p[2], 500)
        self.assertAlmostEqual(p[0], 0.25, delta=0.04)
        self.assertAlmostEqual(p[1], 0.30, delta=0.05)
        self.assertAlmostEqual(e[0], p[0], delta=0.02, msg="export x matches preview x")
        self.assertAlmostEqual(e[1], p[1], delta=0.02, msg="export y matches preview y")

    def test_text_only_during_its_time_range(self):
        title = {"id": "t2", "text": "LATER", "start": 2.0, "duration": 1.5, "position": "center", "x": 0.5, "y": 0.5, "size": 0.12,
                 "rotation": 0, "font": "Arial", "weight": "bold", "color": "#FFFFFF", "opacity": 1.0, "align": "center",
                 "strokeColor": "#000000", "strokeWidth": 0.05, "shadow": False, "background": "", "backgroundOpacity": 0.65,
                 "animation": "none"}
        withs = self.run_job("render", self.doc([title]))
        without = self.run_job("render", self.doc([]))
        a = config.DATA_DIR / withs["result"]["render"]["url"].removeprefix("/files/")
        b = config.DATA_DIR / without["result"]["render"]["url"].removeprefix("/files/")
        _, _, n_out = changed_centroid(a, b, 0.8, self.work)
        _, _, n_in = changed_centroid(a, b, 2.6, self.work)
        self.assertLess(n_out, 150, "nothing before its start time")
        self.assertGreater(n_in, 500, "visible inside its time range")


if __name__ == "__main__":
    unittest.main()
