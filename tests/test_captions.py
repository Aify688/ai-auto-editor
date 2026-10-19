"""AI captions: transcription, word-level sync, karaoke, animations, SRT/VTT and burned-in MP4 export.

Layer 1 (fast) drives the real overlay code with word timings and checks the pixels it produces.
Layer 2 uses real speech, real faster-whisper and real FFmpeg renders/exports (no mocks).

Run:  .venv/bin/python -m unittest -v tests.test_captions
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="frameflow_caps_"))
os.environ["FRAMEFLOW_DATA_DIR"] = str(TMP / "data")

from PIL import Image  # noqa: E402

from video_editor import skills  # noqa: E402
from video_editor.overlay import caption_layer  # noqa: E402

SPEECH = ROOT / "sample_videos" / "speech_real.mp4"
GOLD = (255, 215, 0)
SIZE = (640, 360)


def gold_pixels(img: Image.Image) -> list[int]:
    """x coordinates of fully opaque gold-ish pixels (the highlighted word)."""
    px, xs = img.load(), []
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if a > 200 and r > 220 and 180 < g < 235 and b < 60:
                xs.append(x)
    return xs


def alpha_bbox(img: Image.Image):
    return img.getchannel("A").getbbox()


def items_at(items, t):
    return [i for i in items if i.start <= t < i.end]


def burn_settings(**kw):
    base = {"font_scale": 0.06, "box": False, "position": "bottom", "color": "#FFFFFF", "highlight_color": "#FFD700",
            "outline_color": "#000000", "background": "outline", "karaoke": True, "uppercase": False, "animation": "none"}
    base.update(kw)
    return base


WORDS = [{"word": "alpha", "start": 1.0, "end": 1.5}, {"word": "bravo", "start": 1.5, "end": 2.0},
         {"word": "charlie", "start": 2.0, "end": 2.6}, {"word": "delta", "start": 2.6, "end": 3.0}]
CUE = {"clip": 0, "start": 1.0, "end": 3.0, "text": "alpha bravo charlie delta", "words": WORDS}


class OverlayLogicTest(unittest.TestCase):
    def test_karaoke_highlight_moves_word_by_word(self):
        ctx = skills.OverlayCtx(SIZE, 10.0, [(0, 0.0, 10.0, 0.0)])
        items = skills.overlay_captions(burn_settings(cues=[CUE]), ctx)
        xs = []
        for t in (1.25, 1.75, 2.3, 2.8):
            hit = items_at(items, t)
            self.assertEqual(len(hit), 1, f"exactly one caption image at t={t}")
            g = gold_pixels(hit[0].image)
            self.assertTrue(g, f"a highlighted word at t={t}")
            xs.append(sum(g) / len(g))
        self.assertEqual(xs, sorted(xs), "highlight sweeps left to right")
        self.assertEqual(items_at(items, 0.5), [], "nothing before the cue")
        self.assertEqual(items_at(items, 3.2), [], "nothing after the cue")

    def test_non_karaoke_has_no_highlight(self):
        ctx = skills.OverlayCtx(SIZE, 10.0, [(0, 0.0, 10.0, 0.0)])
        items = skills.overlay_captions(burn_settings(cues=[CUE], karaoke=False), ctx)
        for t in (1.25, 2.3):
            self.assertEqual(gold_pixels(items_at(items, t)[0].image), [])

    def test_timing_follows_trim_split_reorder(self):
        # source 0-10 s cut into [6,10] then [0,4]: the cue (1-3 s) now appears at output 5-7 s
        ctx = skills.OverlayCtx(SIZE, 8.0, [(0, 6.0, 10.0, 0.0), (0, 0.0, 4.0, 4.0)])
        items = skills.overlay_captions(burn_settings(cues=[CUE]), ctx)
        self.assertEqual(items_at(items, 1.0), [])
        self.assertEqual(items_at(items, 4.5), [])
        self.assertAlmostEqual(min(i.start for i in items), 5.0, places=2)
        self.assertAlmostEqual(max(i.end for i in items), 7.0, places=2)
        # 'alpha' (src 1.0-1.5) is highlighted at output 5.0-5.5, 'delta' (2.6-3.0) at 6.6-7.0
        gx = lambda t: sum(gold_pixels(items_at(items, t)[0].image)) / len(gold_pixels(items_at(items, t)[0].image))  # noqa: E731
        self.assertLess(gx(5.25), gx(6.8))

    def test_trimmed_cue_shows_only_the_words_that_remain(self):
        # keep source 2.0-3.0 only: the first half of the cue was cut away
        ctx = skills.OverlayCtx(SIZE, 1.0, [(0, 2.0, 3.0, 0.0)])
        items = skills.overlay_captions(burn_settings(cues=[CUE], karaoke=False), ctx)
        full = skills.overlay_captions(burn_settings(cues=[CUE], karaoke=False),
                                       skills.OverlayCtx(SIZE, 10.0, [(0, 0.0, 10.0, 0.0)]))
        w_part = alpha_bbox(items_at(items, 0.5)[0].image)
        w_full = alpha_bbox(items_at(full, 2.0)[0].image)
        self.assertLess(w_part[2] - w_part[0], w_full[2] - w_full[0], "fewer words -> narrower caption")

    def test_speed_change_rescales_timing(self):
        ctx = skills.OverlayCtx(SIZE, 5.0, [(0, 0.0, 10.0, 0.0)], speed=2.0)
        items = skills.overlay_captions(burn_settings(cues=[CUE]), ctx)
        self.assertAlmostEqual(min(i.start for i in items), 0.5, places=2)
        self.assertAlmostEqual(max(i.end for i in items), 1.5, places=2)

    def test_pop_fade_and_scale_animations(self):
        ctx = skills.OverlayCtx(SIZE, 10.0, [(0, 0.0, 10.0, 0.0)])
        widths = {}
        for kind in ("pop", "scale"):
            items = skills.overlay_captions(burn_settings(cues=[CUE], animation=kind, karaoke=False), ctx)
            first = alpha_bbox(items_at(items, 1.02)[0].image)
            mid = alpha_bbox(items_at(items, 2.0)[0].image)
            widths[kind] = (first[2] - first[0], mid[2] - mid[0])
            self.assertLess(widths[kind][0], widths[kind][1], f"{kind}: starts smaller than the settled caption")
        items = skills.overlay_captions(burn_settings(cues=[CUE], animation="fade", karaoke=False), ctx)
        start_alpha = max(items_at(items, 1.02)[0].image.getchannel("A").getdata())
        settled = max(items_at(items, 2.0)[0].image.getchannel("A").getdata())
        self.assertLess(start_alpha, settled, "fade: translucent at the start")
        self.assertEqual(settled, 255)

    def test_caption_layer_styles(self):
        img = caption_layer(SIZE, ["Hello", "world"], 0, color=(255, 0, 0, 255), highlight=(0, 255, 0, 255))
        self.assertTrue(alpha_bbox(img))
        top = caption_layer(SIZE, ["Hello"], anchor="top")
        bottom = caption_layer(SIZE, ["Hello"], anchor="bottom")
        self.assertLess(alpha_bbox(top)[1], alpha_bbox(bottom)[1])


# --------------------------------------------------------------------------- real pipeline
from fastapi.testclient import TestClient  # noqa: E402
from PIL import ImageChops  # noqa: E402

from backend import config  # noqa: E402
from backend.main import app  # noqa: E402
from backend.services import layout as lay  # noqa: E402
from video_editor import analysis as va  # noqa: E402
from video_editor.ffmpeg_ops import probe_video  # noqa: E402


def wait_job(client, job_id, timeout=600):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.25)
    raise TimeoutError(job_id)


def frame(video: Path, t: float, out: Path) -> Image.Image:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(out)], check=True)
    return Image.open(out).convert("RGB")


def changed_pixels(a: Image.Image, b: Image.Image) -> int:
    diff = ImageChops.difference(a, b).convert("L").point(lambda p: 255 if p > 60 else 0)
    return sum(1 for v in diff.getdata() if v)


class RealCaptionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.pid = cls.client.post("/api/projects", json={"name": "Caps"}).json()["id"]
        with open(SPEECH, "rb") as fh:
            r = cls.client.post(f"/api/projects/{cls.pid}/media", files={"file": (SPEECH.name, fh)})
        cls.mid = r.json()["id"]
        for _ in range(600):
            if cls.client.get(f"/api/projects/{cls.pid}/media").json()[0]["status"] != "processing":
                break
            time.sleep(0.25)
        cls.src_duration = cls.client.get(f"/api/projects/{cls.pid}/media").json()[0]["duration"]
        doc = cls.client.get(f"/api/projects/{cls.pid}").json()["doc"]
        doc.update(style="vlog", aspect="16:9")
        doc["settings"].update(captions=True, removeSilence=True)
        job = cls.run_job(f"/api/projects/{cls.pid}/generate", doc)
        assert job["status"] == "done", job.get("error")
        cls.edl = job["result"]["edl"]
        cls.work = TMP / "frames"
        cls.work.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        shutil.rmtree(TMP, ignore_errors=True)

    @classmethod
    def run_job(cls, path, doc):
        r = cls.client.post(path, json={"doc": doc})
        assert r.status_code == 202, r.text
        return wait_job(cls.client, r.json()["id"])

    def doc(self, **style):
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        doc["edl"]["burnCaptions"] = True
        doc["edl"]["captionStyle"].update(style)
        return doc

    def render(self, doc) -> Path:
        job = self.run_job(f"/api/projects/{self.pid}/render", doc)
        self.assertEqual(job["status"], "done", job.get("error"))
        return config.DATA_DIR / job["result"]["render"]["url"].removeprefix("/files/")

    def baseline(self, doc) -> Path:
        plain = {**doc, "edl": {**doc["edl"], "burnCaptions": False}}
        return self.render(plain)

    # 1. transcription ---------------------------------------------------------------------------
    def test_1_transcription_has_word_timestamps(self):
        text = " ".join(c["text"] for c in self.edl["captions"]).lower()
        for phrase in ("welcome", "pause", "thanks"):
            self.assertIn(phrase, text)
        for c in self.edl["captions"]:
            self.assertTrue(c["words"], "word-level timestamps")
            prev = c["srcStart"] - 0.01
            for w in c["words"]:
                self.assertGreaterEqual(w["start"], prev - 0.05)
                self.assertGreater(w["end"], w["start"])
                self.assertLessEqual(w["end"], self.src_duration + 0.05)
                prev = w["start"]

    # 2. synchronisation with the real audio ---------------------------------------------------
    def test_2_captions_sit_on_speech_not_silence(self):
        src = config.DATA_DIR / "projects" / self.pid / "media"
        path = next(src.glob(f"{self.mid}*"))
        energy = va.audio_energy(path, 0.1)
        loud = max(energy) * 0.15

        def active(t0, t1):
            seg = energy[int(t0 / 0.1): max(int(t0 / 0.1) + 1, int(t1 / 0.1))]
            return sum(1 for e in seg if e > loud) / max(1, len(seg))
        for c in self.edl["captions"]:
            self.assertGreater(active(c["srcStart"], c["srcEnd"]), 0.5, f"caption '{c['text']}' lies on silence")
        # the long pause in the fixture (between sentence 1 and 2) carries no caption
        gaps = [(a["srcEnd"], b["srcStart"]) for a, b in zip(self.edl["captions"], self.edl["captions"][1:]) if b["srcStart"] - a["srcEnd"] > 1.0]
        self.assertTrue(gaps)
        for g0, g1 in gaps:
            self.assertLess(active(g0 + 0.1, g1 - 0.1), 0.2)

    # 3. SRT / VTT ----------------------------------------------------------------------------
    def test_3_srt_and_vtt_exports(self):
        edl = self.client.get(f"/api/projects/{self.pid}").json()["doc"]["edl"]
        clips = [c for c in edl["clips"] if not c.get("rejected") and not c.get("boring")]
        lt = lay.layout(clips, edl["transition"])
        spans = lay.caption_spans(edl["captions"], clips, lt["clips"])
        srt = self.client.get(f"/api/projects/{self.pid}/captions.srt")
        vtt = self.client.get(f"/api/projects/{self.pid}/captions.vtt")
        self.assertEqual((srt.status_code, vtt.status_code), (200, 200))
        self.assertTrue(vtt.text.startswith("WEBVTT"))
        rows = re.findall(r"(\d\d):(\d\d):(\d\d)[,.](\d{3}) --> (\d\d):(\d\d):(\d\d)[,.](\d{3})", srt.text)
        self.assertEqual(len(rows), len(spans))
        for row, sp in zip(rows, spans):
            h, m, sec, ms = map(int, row[:4])
            self.assertAlmostEqual(h * 3600 + m * 60 + sec + ms / 1000, sp["outStart"], delta=0.002)
        self.assertIn(",", srt.text.split("-->")[0].split("\n")[-1])      # SRT uses comma decimals
        self.assertIn(".", vtt.text.split("-->")[0].split("\n")[-1])      # VTT uses dots
        self.assertEqual(self.client.get(f"/api/projects/{self.pid}/captions.txt").status_code, 404)

    # 4. cache ----------------------------------------------------------------------------------
    def test_4_transcription_is_cached(self):
        cache = config.DATA_DIR / "projects" / self.pid / "cache"
        before = sorted(p.name for p in cache.glob("*transcript*"))
        self.assertTrue(before, "first run wrote a transcript cache")
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        t0 = time.time()
        job = self.run_job(f"/api/projects/{self.pid}/transcribe", doc)
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertLess(time.time() - t0, 3.0, "cached transcript is reused, no new speech recognition")
        self.assertEqual(before, sorted(p.name for p in cache.glob("*transcript*")))
        self.assertTrue(job["result"]["captions"])

    # 5. burned-in captions: present in the spans, absent elsewhere; karaoke; MP4 export -------------
    def test_5_burned_captions_match_the_timeline(self):
        doc = self.doc(karaoke=True, animation="none", background="outline", preset="karaoke")
        burned, plain = self.render(doc), self.baseline(doc)
        edl = doc["edl"]
        lt = lay.layout(edl["clips"], edl["transition"])
        spans = lay.caption_spans(edl["captions"], edl["clips"], lt["clips"])
        for i, sp in enumerate(spans):
            t = sp["outStart"] + 0.6 * (sp["outEnd"] - sp["outStart"])
            on = changed_pixels(frame(burned, t, self.work / f"b{i}.png"), frame(plain, t, self.work / f"p{i}.png"))
            self.assertGreater(on, 400, f"caption '{sp['text']}' is visible at {t:.2f}s")
        gap = spans[0]["outEnd"] + 0.12
        if gap < spans[1]["outStart"] - 0.12:
            off = changed_pixels(frame(burned, gap, self.work / "bg.png"), frame(plain, gap, self.work / "pg.png"))
            self.assertLess(off, 150, "no caption between sentences")
        # karaoke: the caption image changes between two words of the same caption
        sp = spans[1]
        a = frame(burned, sp["outStart"] + 0.15, self.work / "k1.png")
        b = frame(burned, sp["outEnd"] - 0.15, self.work / "k2.png")
        self.assertGreater(changed_pixels(a.crop((0, int(a.height * 0.6), a.width, a.height)),
                                          b.crop((0, int(b.height * 0.6), b.width, b.height))), 100)

    def test_6_edited_text_and_reordered_clips_export_correctly(self):
        doc = self.doc(karaoke=False, animation="none", background="outline")
        original = self.render(doc)
        edl = doc["edl"]
        # edit the first caption's text and rebuild its word timings the way the UI does
        cap = edl["captions"][0]
        cap["text"] = "COMPLETELY DIFFERENT WORDS"
        n = len(cap["text"].split())
        step = (cap["srcEnd"] - cap["srcStart"]) / n
        cap["words"] = [{"word": w, "start": cap["srcStart"] + i * step, "end": cap["srcStart"] + (i + 1) * step}
                        for i, w in enumerate(cap["text"].split())]
        # reverse the clips on the timeline
        edl["clips"] = list(reversed(edl["clips"]))
        edited = self.render(doc)
        lt = lay.layout(edl["clips"], edl["transition"])
        spans = lay.caption_spans(edl["captions"], edl["clips"], lt["clips"])
        self.assertTrue(spans)
        plain = self.baseline(doc)
        for i, sp in enumerate(spans):
            t = sp["outStart"] + 0.5 * (sp["outEnd"] - sp["outStart"])
            self.assertGreater(changed_pixels(frame(edited, t, self.work / f"e{i}.png"), frame(plain, t, self.work / f"q{i}.png")), 400,
                               f"caption shown at its new position {t:.2f}s")
        self.assertTrue(any(sp["text"] == "COMPLETELY DIFFERENT WORDS" for sp in spans))
        self.assertAlmostEqual(probe_video(edited).duration, lt["duration"], delta=0.4)
        self.assertNotEqual(original.stat().st_size, edited.stat().st_size)

    def test_7_mp4_export_burns_captions(self):
        doc = self.doc(karaoke=True, animation="pop", background="outline")
        doc["export"] = {"filename": "caps", "resolution": 720, "fps": 30, "quality": "draft", "subtitleHandling": "burn"}
        job = self.run_job(f"/api/projects/{self.pid}/export", doc)
        self.assertEqual(job["status"], "done", job.get("error"))
        out = Path(job["result"]["path"])
        lt = lay.layout(doc["edl"]["clips"], doc["edl"]["transition"])
        self.assertAlmostEqual(probe_video(out).duration, lt["duration"], delta=0.4)
        plain_doc = {**doc, "edl": {**doc["edl"], "burnCaptions": False}}
        plain = self.run_job(f"/api/projects/{self.pid}/export", plain_doc)
        sp = lay.caption_spans(doc["edl"]["captions"], doc["edl"]["clips"], lt["clips"])[0]
        t = sp["outStart"] + 0.6 * (sp["outEnd"] - sp["outStart"])
        self.assertGreater(changed_pixels(frame(out, t, self.work / "x1.png"), frame(Path(plain["result"]["path"]), t, self.work / "x2.png")), 400)


if __name__ == "__main__":
    unittest.main()
