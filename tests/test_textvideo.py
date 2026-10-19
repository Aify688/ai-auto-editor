"""Text-to-video: description-only generation, limits, cancellation and the setup message.

The provider here is a LOCAL TEST DOUBLE that implements the Replicate prediction API contract
(create / poll / cancel / file download) and serves a real ffmpeg-made clip. It proves FrameFlow's side
of the integration (requests, untruncated prompts, polling, download, timeline, render, export). It cannot
prove that a real hosted model accepts the requests: that needs a real REPLICATE_API_TOKEN.

Run:  .venv-1/bin/python -m unittest -v tests.test_textvideo
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="frameflow_t2v_"))
os.environ.setdefault("FRAMEFLOW_DATA_DIR", str(TMP / "data"))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.services import textvideo  # noqa: E402
from video_editor.ffmpeg_ops import probe_video  # noqa: E402

CLIP = TMP / "provider_clip.mp4"


class Provider:
    """In-process stand-in for the hosted API."""
    def __init__(self):
        self.requests: list[dict] = []
        self.auth: set[str] = set()
        self.cancelled = 0
        self.hang = False
        self.polls: dict[str, int] = {}
        prov = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                prov.auth.add(self.headers.get("Authorization", ""))
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if self.path.endswith("/cancel"):
                    prov.cancelled += 1
                    return self._json(200, {"status": "canceled"})
                prov.requests.append(body["input"])
                pid = f"p{len(prov.requests)}"
                base = f"http://127.0.0.1:{prov.port}"
                self._json(201, {"id": pid, "status": "starting",
                                 "urls": {"get": f"{base}/predictions/{pid}", "cancel": f"{base}/predictions/{pid}/cancel"}})

            def do_GET(self):
                if self.path == "/files/clip.mp4":
                    data = CLIP.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    return self.wfile.write(data)
                pid = self.path.rsplit("/", 1)[-1]
                prov.polls[pid] = prov.polls.get(pid, 0) + 1
                if prov.hang or prov.polls[pid] < 2:
                    return self._json(200, {"id": pid, "status": "processing"})
                self._json(200, {"id": pid, "status": "succeeded",
                                 "output": f"http://127.0.0.1:{prov.port}/files/clip.mp4"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()


def wait(client, jid, timeout=600):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.2)
    raise AssertionError("job timed out")


class TextToVideoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-t", "3",
                        "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-t", "3", "-i", "sine=frequency=330",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(CLIP)], check=True)
        cls.prov = Provider()
        cls.env = {"FRAMEFLOW_T2V_BASE_URL": f"http://127.0.0.1:{cls.prov.port}", "FRAMEFLOW_T2V_POLL": "0.05",
                   "FRAMEFLOW_T2V_CLIP_SECONDS": "3", "FRAMEFLOW_T2V_MAX_SCENES": "4"}
        os.environ.update(cls.env)
        os.environ.pop("REPLICATE_API_TOKEN", None)
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.prov.stop()
        for k in cls.env:
            os.environ.pop(k, None)
        os.environ.pop("REPLICATE_API_TOKEN", None)
        shutil.rmtree(TMP, ignore_errors=True)

    def project(self):
        return self.client.post("/api/projects", json={"name": "T2V"}).json()["id"]

    def doc(self, pid, text, **settings):
        doc = self.client.get(f"/api/projects/{pid}").json()["doc"]
        doc["settings"].update(instruction=text, musicSource="none", **settings)
        return doc

    def start(self, pid, doc):
        r = self.client.post(f"/api/projects/{pid}/generate", json={"doc": doc})
        self.assertEqual(r.status_code, 202, r.text)
        return r.json()

    # ------------------------------------------------------------------
    def test_01_nothing_to_generate_is_rejected(self):
        pid = self.project()
        r = self.client.post(f"/api/projects/{pid}/generate", json={"doc": self.doc(pid, "   ")})
        self.assertEqual(r.status_code, 422)
        self.assertIn("describe", r.json()["detail"].lower())

    def test_02_not_configured_fails_with_setup_message_and_no_output(self):
        os.environ.pop("REPLICATE_API_TOKEN", None)
        st = self.client.get("/api/system").json()["textToVideo"]
        self.assertFalse(st["configured"])
        self.assertIn("REPLICATE_API_TOKEN", st["hint"])
        pid = self.project()
        job = wait(self.client, self.start(pid, self.doc(pid, "A fox runs through snow."))["id"])
        self.assertEqual(job["kind"], "textvideo")
        self.assertEqual(job["status"], "failed")
        self.assertIn("REPLICATE_API_TOKEN", job["error"])
        self.assertEqual(self.client.get(f"/api/projects/{pid}/media").json(), [], "no placeholder media is created")
        self.assertIsNone(self.client.get(f"/api/projects/{pid}").json().get("render"))

    def test_03_long_description_is_generated_untruncated_edited_and_exported(self):
        os.environ["REPLICATE_API_TOKEN"] = "test-token-123"
        self.prov.requests.clear()
        paras = [f"Scene {i}: " + ("a lighthouse keeper watches the storm roll over the grey sea, " * 14).strip() + "."
                 for i in range(1, 7)]
        text = "\n\n".join(paras)
        self.assertGreater(len(text), 5000)
        pid = self.project()
        st = self.client.get("/api/system").json()
        self.assertTrue(st["textToVideo"]["configured"])
        self.assertNotIn("test-token-123", json.dumps(st), "the token is never exposed")

        plan = self.client.post(f"/api/projects/{pid}/generation/plan", json={"doc": self.doc(pid, text)}).json()
        self.assertEqual(plan["mode"], "text")
        self.assertLessEqual(plan["sceneCount"], 4)   # 6 paragraphs grouped within the 4-scene cap
        count = plan["sceneCount"]

        job = wait(self.client, self.start(pid, self.doc(pid, text))["id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual(job["kind"], "textvideo")
        self.assertEqual(self.prov.auth, {"Bearer test-token-123"})
        sent = [r["prompt"] for r in self.prov.requests]
        self.assertEqual(len(sent), count)
        self.assertTrue(all(len(p) <= textvideo.PROMPT_LIMIT for p in sent))
        squash = lambda s: re.sub(r"\s+", " ", s)  # noqa: E731
        self.assertEqual(squash(" ".join(sent)), squash(text), "every character of the description reached the provider")

        res = job["result"]
        edl = res["edl"]
        self.assertEqual(len(edl["clips"]), count)
        self.assertEqual(res["appliedDoc"]["settings"]["instruction"], text)
        media = self.client.get(f"/api/projects/{pid}/media").json()
        self.assertEqual({m["status"] for m in media}, {"ready"})
        self.assertEqual(len(media), count)
        self.assertGreater(res["render"]["duration"], 8)
        doc = self.client.get(f"/api/projects/{pid}").json()["doc"]
        self.assertEqual(len(doc["edl"]["clips"]), count, "the timeline is populated and persisted")
        self.assertEqual(doc["settings"]["instruction"], text, "the description is saved with the project")

        # manual edit on the generated timeline, re-render, then export a real file
        doc["edl"]["clips"][0]["srcEnd"] = 2.0
        job = wait(self.client, self.client.post(f"/api/projects/{pid}/render", json={"doc": doc}).json()["id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        doc["export"] = {"filename": "generated", "resolution": 720, "fps": 30, "quality": "draft"}
        job = wait(self.client, self.client.post(f"/api/projects/{pid}/export", json={"doc": doc}).json()["id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        info = probe_video(Path(job["result"]["path"]))
        self.assertGreater(info.duration, 4)
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/download").status_code, 200)

    def test_04_description_too_long_for_the_provider_fails_clearly(self):
        os.environ["REPLICATE_API_TOKEN"] = "t"
        self.prov.requests.clear()
        text = "\n\n".join("word " * 300 for _ in range(12))       # ~18,000 chars > 4 scenes x 1,800
        self.assertLess(len(text), 20000)
        pid = self.project()
        job = wait(self.client, self.start(pid, self.doc(pid, text))["id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("too long", job["error"])
        self.assertEqual(self.prov.requests, [], "nothing is truncated or half-sent")

    def test_05_requested_length_beyond_the_limit_is_reported(self):
        os.environ["REPLICATE_API_TOKEN"] = "t"
        text = " ".join(f"Shot {i}: a calm lake at dawn." for i in range(10))
        sp = textvideo.plan(text, 60, "16:9")
        self.assertEqual(sp["sceneCount"], 4)
        self.assertTrue(any("limited to 4 scenes" in n for n in sp["notes"]))
        short = textvideo.plan("A calm lake at dawn.", 60, "16:9")
        self.assertEqual(short["sceneCount"], 1)
        self.assertTrue(any("Describe more scenes" in n for n in short["notes"]))

    def test_06_cancel_stops_the_job_and_the_provider_prediction(self):
        os.environ["REPLICATE_API_TOKEN"] = "t"
        self.prov.hang, before = True, self.prov.cancelled
        try:
            pid = self.project()
            jid = self.start(pid, self.doc(pid, "A ship in a bottle."))["id"]
            for _ in range(100):
                if self.prov.requests and self.client.get(f"/api/jobs/{jid}").json()["status"] == "running":
                    break
                time.sleep(0.1)
            time.sleep(0.3)
            self.client.post(f"/api/jobs/{jid}/cancel")
            self.assertEqual(wait(self.client, jid)["status"], "cancelled")
            self.assertGreater(self.prov.cancelled, before, "the provider prediction was cancelled too")
        finally:
            self.prov.hang = False

    def test_07_uploaded_footage_still_uses_the_auto_edit_pipeline(self):
        os.environ["REPLICATE_API_TOKEN"] = "t"
        pid = self.project()
        with open(CLIP, "rb") as fh:
            self.assertEqual(self.client.post(f"/api/projects/{pid}/media", files={"file": ("a.mp4", fh)}).status_code, 201)
        for _ in range(200):
            if self.client.get(f"/api/projects/{pid}/media").json()[0]["status"] != "processing":
                break
            time.sleep(0.2)
        self.prov.requests.clear()
        plan = self.client.post(f"/api/projects/{pid}/generation/plan", json={"doc": self.doc(pid, "make it punchy")}).json()
        self.assertEqual(plan["mode"], "edit")
        job = wait(self.client, self.start(pid, self.doc(pid, "make it punchy"))["id"])
        self.assertEqual(job["kind"], "generate")
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual(self.prov.requests, [], "no text-to-video request when footage is present")


if __name__ == "__main__":
    unittest.main()
