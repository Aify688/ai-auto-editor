"""Music: search, preview, add (with licence rules), Auto-edit keeping the user's choice, and export credits.
Jamendo is replaced by a local server speaking its API shape, so this proves our side, not Jamendo's catalogue."""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="music_test_"))
os.environ["FRAMEFLOW_DATA_DIR"] = str(TMP / "data")

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from tests import fixtures  # noqa: E402

FIX = fixtures.make(TMP / "fixtures")
MP3 = ROOT / "backend" / "assets" / "music" / "relaxing.mp3"
TRACKS = [
    {"id": "1", "name": "Sunny Day", "artist_name": "Alice Wave", "duration": 90, "license_ccurl": "https://creativecommons.org/licenses/by/3.0/",
     "shareurl": "https://www.jamendo.com/track/1", "audio": "{base}/a/1.mp3", "musicinfo": {"tags": {"genres": ["pop"], "vartags": ["happy"]}}},
    {"id": "2", "name": "Hard Beat", "artist_name": "Bob", "duration": 120, "license_ccurl": "https://creativecommons.org/licenses/by-nc-sa/3.0/",
     "shareurl": "https://www.jamendo.com/track/2", "audio": "{base}/a/2.mp3", "musicinfo": {"tags": {"genres": ["rock"], "vartags": ["energetic"]}}},
]
SEEN: list = []


class FakeJamendo(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        base = f"http://127.0.0.1:{self.server.server_port}"
        if u.path.startswith("/a/"):
            data = MP3.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        SEEN.append(q)
        if q.get("client_id") != "good-id":
            body = {"headers": {"status": "failed", "error_message": "invalid client"}, "results": []}
        else:
            res = TRACKS
            if "id" in q:
                res = [t for t in TRACKS if t["id"] == q["id"]]
            elif "search" in q or "fuzzytags" in q:
                term = (q.get("search") or q.get("fuzzytags")).lower()
                res = [t for t in TRACKS if term in t["name"].lower() or term in t["artist_name"].lower()
                       or term in json.dumps(t["musicinfo"]).lower()]
            res = [{**t, "audio": t["audio"].format(base=base)} for t in res]
            body = {"headers": {"status": "success"}, "results": res}
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def wait(client, job_id, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.25)
    raise TimeoutError(job_id)


class MusicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeJamendo)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.pid = cls.client.post("/api/projects", json={"name": "Music"}).json()["id"]
        with open(FIX["multiscene"], "rb") as fh:
            cls.client.post(f"/api/projects/{cls.pid}/media", files={"file": ("a.mp4", fh)})
        cls.wait_media()

    @classmethod
    def wait_media(cls):
        for _ in range(400):
            m = cls.client.get(f"/api/projects/{cls.pid}/media").json()
            if all(x["status"] != "processing" for x in m):
                return m
            time.sleep(0.25)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.client.__exit__(None, None, None)
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        os.environ.pop("JAMENDO_CLIENT_ID", None)
        os.environ["JAMENDO_BASE_URL"] = f"http://127.0.0.1:{self.server.server_port}"

    def test_unconfigured_explains_setup_but_library_still_searchable(self):
        st = self.client.get("/api/music/status").json()
        jam = next(p for p in st["providers"] if p["id"] == "jamendo")
        self.assertFalse(jam["configured"])
        self.assertIn("JAMENDO_CLIENT_ID", jam["hint"])
        r = self.client.get("/api/music/search", params={"q": "relaxing"}).json()
        self.assertEqual([t["title"] for t in r["results"]], ["Home"])
        self.assertEqual(r["results"][0]["artist"], "Tanner Helland")
        self.assertIn("CC BY 4.0", r["results"][0]["license"]["label"])
        self.assertTrue(any("JAMENDO_CLIENT_ID" in n for n in r["notices"]))
        self.assertEqual(self.client.get("/api/music/search", params={"q": "tanner"}).json()["results"].__len__(), 5)

    def test_search_preview_add_and_licence_rules(self):
        os.environ["JAMENDO_CLIENT_ID"] = "good-id"
        r = self.client.get("/api/music/search", params={"q": "pop"}).json()
        ids = [t["id"] for t in r["results"]]
        self.assertIn("jamendo:1", ids)
        self.assertNotIn("jamendo:2", ids)                                   # NC/ND hidden by default
        track = next(t for t in r["results"] if t["id"] == "jamendo:1")
        self.assertEqual((track["title"], track["artist"], track["duration"]), ("Sunny Day", "Alice Wave", 90.0))
        self.assertEqual(track["license"]["label"], "CC BY 3.0")
        self.assertNotIn("good-id", json.dumps(r))                            # the client id never reaches the browser
        both = self.client.get("/api/music/search", params={"q": "beat", "restricted": "true"}).json()["results"]
        self.assertEqual(both[0]["license"]["commercialOk"], False)
        n_audio = lambda: len([m for m in self.client.get(f"/api/projects/{self.pid}/media").json() if m["kind"] == "audio"])  # noqa: E731
        before = n_audio()
        prev = self.client.get(track["previewUrl"])                           # previewing adds nothing
        self.assertEqual(prev.status_code, 200)
        self.assertEqual(prev.headers["content-type"], "audio/mpeg")
        self.assertGreater(len(prev.content), 10000)
        self.assertEqual(n_audio(), before)
        bad = self.client.post(f"/api/projects/{self.pid}/music/add", json={"trackId": "jamendo:2"})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("CC BY-NC-SA", bad.json()["detail"])
        ok = self.client.post(f"/api/projects/{self.pid}/music/add", json={"trackId": "jamendo:1"})
        self.assertEqual(ok.status_code, 201, ok.text)
        self.assertIn("Alice Wave", ok.json()["attribution"])
        self.wait_media()
        again = self.client.post(f"/api/projects/{self.pid}/music/add", json={"trackId": "jamendo:1"}).json()
        self.assertEqual(again["mediaId"], ok.json()["mediaId"])               # adding twice reuses the same media
        m = next(x for x in self.client.get(f"/api/projects/{self.pid}/media").json() if x["id"] == ok.json()["mediaId"])
        self.assertEqual((m["kind"], m["status"]), ("audio", "ready"))
        self.assertIn("CC BY 3.0", m["info"]["attribution"]["license"])

    def test_bad_client_id_is_reported(self):
        os.environ["JAMENDO_CLIENT_ID"] = "wrong"
        r = self.client.get("/api/music/search", params={"q": "pop"}).json()
        self.assertTrue(any("invalid client" in n for n in r["notices"]))
        self.assertTrue(r["results"] == [] or all(t["provider"] == "library" for t in r["results"]))

    def test_autoedit_keeps_chosen_music_adjustments_and_never_duplicates(self):
        os.environ["JAMENDO_CLIENT_ID"] = "good-id"
        add = self.client.post(f"/api/projects/{self.pid}/music/add", json={"trackId": "jamendo:1"}).json()
        self.wait_media()
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        doc["settings"].update(musicMode="choose", musicSource="upload", musicId=add["mediaId"], captions=False, removeFillers=False)
        chosen = {"id": "mine", "mediaId": add["mediaId"], "kind": "music", "start": 0.5, "trimIn": 3.0, "duration": 4.0,
                  "volume": 0.6, "fadeIn": 1.0, "fadeOut": 1.5, "loop": False, "duck": True, "effect": "none"}
        doc["edl"] = {"version": 1, "style": "dynamic", "aspect": "16:9", "fit": "crop", "clips": [], "transition": None,
                      "look": "none", "music": None, "audioClips": [chosen, {**chosen, "id": "vo", "kind": "audio", "mediaId": add["mediaId"]}],
                      "markers": [], "captions": [], "captionStyle": {}, "burnCaptions": False, "titles": [],
                      "audio": {"normalize": True, "lufs": -14, "clean": False, "fades": False}, "beat": None, "notes": [],
                      "videoType": None, "resolvedStyle": None}
        doc["edl"].pop("captionStyle")
        for _ in range(2):                                                   # run it twice: still one music track
            r = self.client.post(f"/api/projects/{self.pid}/generate", json={"doc": doc})
            self.assertEqual(r.status_code, 202, r.text)
            job = wait(self.client, r.json()["id"])
            self.assertEqual(job["status"], "done", job["error"])
            clips = job["result"]["edl"]["audioClips"]
            music = [c for c in clips if c["kind"] == "music"]
            self.assertEqual(len(music), 1)
            m = music[0]
            self.assertEqual((m["id"], m["start"], m["trimIn"], m["volume"], m["fadeIn"], m["fadeOut"], m["duck"]),
                             ("mine", 0.5, 3.0, 0.6, 1.0, 1.5, True))
            self.assertEqual([c["id"] for c in clips if c["kind"] == "audio"], ["vo"])   # added sounds are kept too
            doc["edl"] = job["result"]["edl"]
        # "No music" stays off; Auto (never chosen) adds exactly one generated track
        doc["settings"].update(musicMode="none", musicSource="none", musicId=None)
        job = wait(self.client, self.client.post(f"/api/projects/{self.pid}/generate", json={"doc": doc}).json()["id"])
        self.assertEqual([c for c in job["result"]["edl"]["audioClips"] if c["kind"] == "music"], [])
        doc["settings"].update(musicMode=None, musicSource="auto")
        doc["edl"] = job["result"]["edl"]
        job = wait(self.client, self.client.post(f"/api/projects/{self.pid}/generate", json={"doc": doc}).json()["id"])
        self.assertEqual(len([c for c in job["result"]["edl"]["audioClips"] if c["kind"] == "music"]), 1)
        self.edl = job["result"]["edl"]

    def test_export_writes_music_credits(self):
        os.environ["JAMENDO_CLIENT_ID"] = "good-id"
        add = self.client.post(f"/api/projects/{self.pid}/music/add", json={"trackId": "jamendo:1"}).json()
        self.wait_media()
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        doc["settings"].update(musicMode="choose", musicSource="upload", musicId=add["mediaId"], captions=False)
        job = wait(self.client, self.client.post(f"/api/projects/{self.pid}/generate", json={"doc": doc}).json()["id"])
        self.assertEqual(job["status"], "done", job["error"])
        edl = job["result"]["edl"]
        edl["audioClips"] = [{**c, "mediaId": add["mediaId"], "kind": "music"} for c in edl["audioClips"][:1]] or [{
            "id": "m", "mediaId": add["mediaId"], "kind": "music", "start": 0, "trimIn": 0, "duration": None, "volume": 0.35,
            "fadeIn": 0, "fadeOut": 0, "loop": True, "duck": True}]
        doc["edl"] = edl
        doc["export"] = {"filename": "withmusic", "resolution": 720, "fps": 30, "quality": "draft"}
        job = wait(self.client, self.client.post(f"/api/projects/{self.pid}/export", json={"doc": doc}).json()["id"])
        self.assertEqual(job["status"], "done", job["error"])
        res = job["result"]
        self.assertTrue(any("Alice Wave" in c and "CC BY 3.0" in c for c in res["credits"]))
        credits = Path(res["path"]).with_suffix(".credits.txt")
        self.assertTrue(credits.exists())
        self.assertIn("Sunny Day", credits.read_text())
        from video_editor.ffmpeg_ops import probe_video
        self.assertTrue(probe_video(Path(res["path"])).has_audio)


if __name__ == "__main__":
    unittest.main()
