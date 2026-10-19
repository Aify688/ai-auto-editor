"""Multi-video AI editing: every uploaded video must contribute, and boring footage must really be cut.

Real FFmpeg fixtures, real analysis, real render and export (no mocks).

Run:  .venv/bin/python -m unittest -v tests.test_multivideo
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="frameflow_multi_"))
os.environ["FRAMEFLOW_DATA_DIR"] = str(TMP / "data")

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.services import layout as lay  # noqa: E402
from video_editor.ffmpeg_ops import probe_video  # noqa: E402

# Ground truth (seconds) for the generated fixtures.
A_BLANK = (5.0, 11.0)        # flat grey picture, tone muted -> boring
A_SILENT_ACTION = (17.0, 21.0)   # tone muted but the picture is moving -> meaningful, keep
B_BLANK = (6.0, 10.0)        # flat picture, tone continues


def _ff(*args: str) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-600:])


def make_fixtures(folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    a, b = folder / "A_talk.mp4", folder / "B_scenery.mp4"
    shot = "format=yuv420p,setsar=1"
    _ff("-f", "lavfi", "-t", "5", "-i", "testsrc2=size=1280x720:rate=30",
        "-f", "lavfi", "-t", "6", "-i", "color=c=0x303030:size=1280x720:rate=30",
        "-f", "lavfi", "-t", "6", "-i", "mandelbrot=size=1280x720:rate=30:start_scale=3:end_scale=0.002",
        "-f", "lavfi", "-t", "4", "-i", "life=size=1280x720:rate=30:mold=10:ratio=0.2:death_color=#203040:life_color=#ffcc00",
        "-f", "lavfi", "-t", "4", "-i", "cellauto=size=1280x720:rate=30:rule=110,negate",
        "-f", "lavfi", "-i", "sine=frequency=220:duration=25,volume='if(between(t,5,11)+between(t,17,21),0,0.5)':eval=frame",
        "-filter_complex", ";".join(f"[{i}:v]{shot}[v{i}]" for i in range(5)) + ";" +
        "".join(f"[v{i}]" for i in range(5)) + "concat=n=5:v=1:a=0[v]",
        "-map", "[v]", "-map", "5:a", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(a))
    _ff("-f", "lavfi", "-t", "6", "-i", "life=size=1280x720:rate=30:mold=10:ratio=0.1:death_color=#102040:life_color=#40ff80",
        "-f", "lavfi", "-t", "4", "-i", "color=c=0x202020:size=1280x720:rate=30",
        "-f", "lavfi", "-t", "8", "-i", "mandelbrot=size=1280x720:rate=30:start_scale=1:end_scale=0.01",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=18,volume=0.4",
        "-filter_complex", ";".join(f"[{i}:v]{shot}[v{i}]" for i in range(3)) + ";[v0][v1][v2]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(b))
    return a, b


def wait_job(client, job_id, timeout=600):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.25)
    raise TimeoutError(job_id)


def overlap(c, rng):
    return max(0.0, min(c["srcEnd"], rng[1]) - max(c["srcStart"], rng[0]))


class MultiVideoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        a, b = make_fixtures(TMP / "fixtures")
        cls.pid = cls.client.post("/api/projects", json={"name": "Multi"}).json()["id"]
        cls.ids = {}
        for key, path in (("A", a), ("B", b)):
            with open(path, "rb") as fh:
                r = cls.client.post(f"/api/projects/{cls.pid}/media", files={"file": (path.name, fh)})
            assert r.status_code == 201, r.text
            cls.ids[key] = r.json()["id"]
        for _ in range(600):
            media = cls.client.get(f"/api/projects/{cls.pid}/media").json()
            if all(m["status"] != "processing" for m in media):
                break
            time.sleep(0.25)
        cls.durations = {m["id"]: m["duration"] for m in media}

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        shutil.rmtree(TMP, ignore_errors=True)

    def generate(self, style=None, **settings) -> dict:
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        doc["settings"].update(settings)
        if style:
            doc["style"] = style
        r = self.client.post(f"/api/projects/{self.pid}/generate", json={"doc": doc})
        self.assertEqual(r.status_code, 202, r.text)
        job = wait_job(self.client, r.json()["id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        return job["result"]

    def seconds(self, edl, key) -> float:
        return sum(c["srcEnd"] - c["srcStart"] for c in edl["clips"] if c["mediaId"] == self.ids[key])

    def test_1_default_edit_uses_every_video(self):
        res = self.generate()
        edl = res["edl"]
        self.assertGreater(self.seconds(edl, "A"), 1.5, edl["notes"])
        self.assertGreater(self.seconds(edl, "B"), 1.5, edl["notes"])
        # source ids and ranges are valid and never reuse the same footage twice
        for c in edl["clips"]:
            self.assertIn(c["mediaId"], self.ids.values())
            self.assertGreaterEqual(c["srcStart"], 0)
            self.assertLess(c["srcStart"], c["srcEnd"])
            self.assertLessEqual(c["srcEnd"], self.durations[c["mediaId"]] + 1e-3)
        for mid in self.ids.values():
            mine = sorted((c for c in edl["clips"] if c["mediaId"] == mid), key=lambda c: c["srcStart"])
            for p, q in zip(mine, mine[1:]):
                self.assertLessEqual(p["srcEnd"], q["srcStart"] + 1e-3, "overlapping source ranges")
        self.assertEqual(edl["excluded"], [])

    def test_2_boring_sections_are_actually_removed(self):
        edl = self.generate()["edl"]
        for c in edl["clips"]:
            if c["mediaId"] == self.ids["A"]:
                self.assertLess(overlap(c, A_BLANK), 0.3, f"clip {c['srcStart']}-{c['srcEnd']} sits in the blank block")
            else:
                self.assertLess(overlap(c, B_BLANK), 0.3, f"clip {c['srcStart']}-{c['srcEnd']} sits in the blank block")
        removed = [(r["mediaId"], r["start"], r["end"], r["reason"]) for r in edl["removed"]]
        self.assertTrue(any(m == self.ids["A"] and s < 6 and e > 10 for m, s, e, _ in removed), removed)
        self.assertTrue(any(m == self.ids["B"] and s < 7 and e > 9 for m, s, e, _ in removed), removed)
        # silent but visibly active footage is not treated as boring
        for m, s, e, _ in removed:
            if m == self.ids["A"]:
                self.assertLess(max(0.0, min(e, A_SILENT_ACTION[1]) - max(s, A_SILENT_ACTION[0])), 1.0,
                                "silent-but-moving footage was cut")

    def test_3_render_and_export_match_the_edl(self):
        res = self.generate()
        edl = res["edl"]
        expected = lay.layout(edl["clips"], edl["transition"])["duration"]
        self.assertAlmostEqual(probe_video(self._render_file(res["render"])).duration, expected, delta=0.6)
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        r = self.client.post(f"/api/projects/{self.pid}/export", json={"doc": doc})
        self.assertEqual(r.status_code, 202, r.text)
        job = wait_job(self.client, r.json()["id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        out = Path(job["result"]["path"])
        self.assertTrue(out.exists())
        self.assertAlmostEqual(probe_video(out).duration, expected, delta=0.8)

    def _render_file(self, render) -> Path:
        from backend import config
        return config.DATA_DIR / render["url"].split("/files/", 1)[1]

    def test_4_short_target_keeps_all_videos_and_reports(self):
        edl = self.generate(style="cinematic", targetDuration=5, beatSync=False)["edl"]
        self.assertGreater(self.seconds(edl, "A"), 0)
        self.assertGreater(self.seconds(edl, "B"), 0)
        self.assertTrue(any("target" in n.lower() for n in edl["notes"]), edl["notes"])

    def test_5_light_intensity_keeps_more_than_aggressive(self):
        light = self.generate(intensity="light", targetDuration=40)["edl"]
        aggressive = self.generate(intensity="aggressive", targetDuration=40)["edl"]
        cut = lambda e: sum(r["end"] - r["start"] for r in e["removed"])  # noqa: E731
        self.assertLessEqual(cut(light), cut(aggressive) + 1e-6)


if __name__ == "__main__":
    unittest.main()
