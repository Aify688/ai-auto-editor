"""Image to Animation: the whole job against a local stand-in for the provider's HTTP API (the pipeline, not the
provider's model, is what this proves)."""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="i2v_test_"))
os.environ["FRAMEFLOW_DATA_DIR"] = str(TMP / "data")

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from tests import fixtures  # noqa: E402
from video_editor.ffmpeg_ops import probe_video  # noqa: E402

FIX = fixtures.make(TMP / "fixtures")
SEEN: dict = {}


class FakeProvider(BaseHTTPRequestHandler):
    video = FIX["multiscene"]          # a real 16:9 clip longer than the requested length

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
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN["auth"] = self.headers.get("Authorization")
        SEEN["path"] = self.path
        SEEN["input"] = body["input"]
        self._json(201, {"id": "p1", "status": "starting", "urls": {"get": f"http://127.0.0.1:{self.server.server_port}/predictions/p1"}})

    def do_GET(self):
        if self.path.startswith("/predictions/"):
            self._json(200, {"id": "p1", "status": "succeeded", "output": f"http://127.0.0.1:{self.server.server_port}/out.mp4"})
        else:
            data = Path(self.video).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)


def wait(client, job_id, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.25)
    raise TimeoutError(job_id)


class ImageToVideoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeProvider)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.pid = cls.client.post("/api/projects", json={"name": "I2V"}).json()["id"]
        with open(FIX["still"], "rb") as fh:
            cls.img = cls.client.post(f"/api/projects/{cls.pid}/media", files={"file": ("photo.jpg", fh)}).json()
        for _ in range(200):
            m = cls.client.get(f"/api/projects/{cls.pid}/media").json()
            if all(x["status"] != "processing" for x in m):
                break
            time.sleep(0.25)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.client.__exit__(None, None, None)
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        for k in ("REPLICATE_API_TOKEN", "FRAMEFLOW_T2V_BASE_URL", "FRAMEFLOW_T2V_POLL"):
            os.environ.pop(k, None)

    def test_not_configured_explains_setup(self):
        st = self.client.get("/api/system/image-to-video").json()
        self.assertFalse(st["configured"])
        self.assertIn("REPLICATE_API_TOKEN", st["hint"])
        r = self.client.post(f"/api/projects/{self.pid}/animate", json={"mediaId": self.img["id"]})
        self.assertEqual(r.status_code, 503)
        self.assertIn("REPLICATE_API_TOKEN", r.json()["detail"])

    def test_animate_end_to_end(self):
        os.environ["REPLICATE_API_TOKEN"] = "test-token"
        os.environ["FRAMEFLOW_T2V_BASE_URL"] = f"http://127.0.0.1:{self.server.server_port}"
        os.environ["FRAMEFLOW_T2V_POLL"] = "0.1"
        before = os.path.getsize(FIX["still"])
        r = self.client.post(f"/api/projects/{self.pid}/animate",
                             json={"mediaId": self.img["id"], "seconds": 2, "aspect": "9:16", "intensity": "high", "prompt": ""})
        self.assertEqual(r.status_code, 202, r.text)
        dup = self.client.post(f"/api/projects/{self.pid}/animate", json={"mediaId": self.img["id"]})
        self.assertEqual(dup.status_code, 409)           # no duplicate submissions while one is running
        job = wait(self.client, r.json()["id"])
        self.assertEqual(job["status"], "done", job["error"])
        res = job["result"]
        self.assertEqual(SEEN["auth"], "Bearer test-token")
        self.assertTrue(SEEN["input"]["image"].startswith("data:image/jpeg;base64,"))
        self.assertIn("identity", SEEN["input"]["prompt"])      # auto prompt keeps the subject
        self.assertIn("lively", SEEN["input"]["prompt"])        # intensity reaches the prompt
        media = {m["id"]: m for m in self.client.get(f"/api/projects/{self.pid}/media").json()}
        out = media[res["mediaId"]]
        self.assertEqual((out["kind"], out["status"]), ("video", "ready"))
        self.assertAlmostEqual(out["duration"], 2.0, delta=0.15)           # trimmed to the requested length
        self.assertLess(out["width"], out["height"])                       # cropped to 9:16
        self.assertIn(self.img["id"], media)                               # the image is still there
        self.assertEqual(os.path.getsize(FIX["still"]), before)

    def test_user_prompt_is_used_and_provider_errors_are_shown(self):
        os.environ["REPLICATE_API_TOKEN"] = "bad"
        os.environ["FRAMEFLOW_T2V_BASE_URL"] = "http://127.0.0.1:9"      # nothing listens here
        r = self.client.post(f"/api/projects/{self.pid}/animate", json={"mediaId": self.img["id"], "prompt": "Clouds drift left"})
        job = wait(self.client, r.json()["id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("Could not reach the video provider", job["error"])


if __name__ == "__main__":
    unittest.main()
