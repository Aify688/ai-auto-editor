"""Instruction -> plan, templates vs styles, music recommendations and target-length conflicts, on real footage.

Run:  .venv/bin/python -m unittest -v tests.test_ai_plan
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="frameflow_plan_"))
os.environ.setdefault("FRAMEFLOW_DATA_DIR", str(TMP / "data"))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.schemas import ProjectDoc  # noqa: E402
from backend.services import instructions, music_library, templates  # noqa: E402
from tests.test_multivideo import make_fixtures  # noqa: E402

SPEECH = ROOT / "sample_videos" / "speech_real.mp4"
INSTRUCTION = "Create a 30-second travel vlog with upbeat music, dynamic captions and smooth transitions."


class InstructionParsingTest(unittest.TestCase):
    def test_example_request(self):
        p = instructions.parse(INSTRUCTION)
        self.assertEqual(p["settings"]["targetDuration"], 30)
        self.assertEqual(p["settings"]["musicSource"], "auto")
        self.assertEqual(p["settings"]["musicMood"], "energetic")
        self.assertTrue(p["settings"]["captions"])
        self.assertTrue(p["settings"]["transitions"])
        self.assertEqual(p["captionPreset"], "dynamic")
        self.assertEqual(p["template"], "travel_recap")
        self.assertEqual(p["style"], "vlog", "explicit 'vlog' beats the generic 'upbeat'")
        self.assertEqual(p["warnings"], [])

    def test_variants(self):
        self.assertEqual(instructions.parse("a calm 2 minute birthday video")["settings"]["targetDuration"], 120)
        self.assertEqual(instructions.parse("a calm birthday video with music")["settings"]["musicMood"], "relaxing")
        self.assertEqual(instructions.parse("vertical reel, no music, no captions")["aspect"], "9:16")
        p = instructions.parse("vertical reel, no music, no captions")
        self.assertEqual((p["settings"]["musicSource"], p["settings"]["captions"]), ("none", False))
        self.assertEqual(instructions.parse("karaoke captions in Spanish")["settings"]["subtitleLanguage"], "es")
        self.assertEqual(instructions.parse("documentary about my town")["style"], "documentary")

    def test_nothing_understood_changes_nothing_and_bad_values_warn(self):
        self.assertEqual(instructions.parse("")["settings"], {})
        self.assertEqual(instructions.parse("make it nice")["understood"], [])
        w = instructions.parse("make it 2000 seconds")
        self.assertNotIn("targetDuration", w["settings"])
        self.assertTrue(w["warnings"])

    def test_apply_is_pure_and_validated(self):
        doc = ProjectDoc()
        before = doc.model_dump()
        out = instructions.apply(doc, instructions.parse(INSTRUCTION))
        self.assertEqual(doc.model_dump(), before, "the stored document is not modified")
        self.assertEqual(out.settings.targetDuration, 30)
        self.assertEqual(out.template, "travel_recap")
        self.assertEqual(out.settings.captionPreset, "dynamic")

    def test_styles_and_templates_are_separate_catalogues(self):
        from backend.services.editing import STYLES
        for k in ("cinematic", "energetic", "minimal", "vlog", "documentary", "professional"):
            self.assertIn(k, STYLES)
        self.assertEqual(set(templates.TEMPLATES), {"travel_recap", "birthday_memories", "product_showcase", "fitness_montage", "social_reel"})
        self.assertFalse(set(templates.TEMPLATES) & set(STYLES))


class RealPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        a, b = make_fixtures(TMP / "fixtures")
        cls.pid = cls.client.post("/api/projects", json={"name": "Plan"}).json()["id"]
        cls.names = {}
        for path in (a, b, SPEECH):
            with open(path, "rb") as fh:
                r = cls.client.post(f"/api/projects/{cls.pid}/media", files={"file": (path.name, fh)})
            assert r.status_code == 201, r.text
            cls.names[r.json()["id"]] = path.name
        for _ in range(900):
            if all(m["status"] != "processing" for m in cls.client.get(f"/api/projects/{cls.pid}/media").json()):
                break
            time.sleep(0.25)

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        shutil.rmtree(TMP, ignore_errors=True)

    def generate(self, instruction="", **doc_patch):
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        doc["settings"].update(instruction=instruction)
        for k, v in doc_patch.pop("settings", {}).items():
            doc["settings"][k] = v
        doc.update(doc_patch)
        r = self.client.post(f"/api/projects/{self.pid}/generate", json={"doc": doc})
        self.assertEqual(r.status_code, 202, r.text)
        end = time.time() + 600
        while time.time() < end:
            j = self.client.get(f"/api/jobs/{r.json()['id']}").json()
            if j["status"] not in ("queued", "running"):
                break
            time.sleep(0.25)
        self.assertEqual(j["status"], "done", j.get("error"))
        return j["result"]

    def seconds(self, edl):
        per = {}
        for c in edl["clips"]:
            per[c["mediaId"]] = per.get(c["mediaId"], 0) + c["srcEnd"] - c["srcStart"]
        return per

    def test_01_music_recommendations_before_analysis_use_the_style_and_say_so(self):
        r = self.client.get(f"/api/projects/{self.pid}/music-recommendations")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["basis"], "style")
        self.assertEqual(len(r.json()["tracks"]), 3)

    def test_02_instruction_drives_a_complete_validated_edit(self):
        res = self.generate(INSTRUCTION)
        edl = res["edl"]
        total = sum(c["srcEnd"] - c["srcStart"] for c in edl["clips"])
        self.assertAlmostEqual(total, 30, delta=2.5, msg="the 30 s request is respected")
        self.assertEqual(set(self.seconds(edl)), set(self.names), "every uploaded video is used")
        self.assertEqual(edl["captionStyle"]["preset"], "dynamic")
        self.assertEqual(edl["music"]["mediaId"], "lib:energetic")
        self.assertTrue(edl["captions"], "speech captions were generated")
        self.assertEqual(edl["plan"]["instruction"], INSTRUCTION)
        self.assertIn("30 s long", edl["plan"]["understood"])
        self.assertEqual(res["appliedDoc"]["style"], "vlog")
        self.assertEqual(res["appliedDoc"]["template"], "travel_recap")
        self.assertEqual(res["appliedDoc"]["settings"]["targetDuration"], 30)
        # template laid out as contiguous sections with editable text placeholders
        secs = edl["template"]["sections"]
        self.assertGreaterEqual(len(secs), 3)
        self.assertEqual(secs[0]["start"], 0)
        for p, q in zip(secs, secs[1:]):
            self.assertAlmostEqual(p["end"], q["start"], places=2)
        self.assertTrue(any(t["text"] == "Where we went" and t["start"] == 0 for t in edl["titles"]))
        self.assertTrue(res["render"]["duration"] > 20)

    def test_03_stored_project_keeps_the_users_own_settings(self):
        doc = self.client.get(f"/api/projects/{self.pid}").json()["doc"]
        self.assertEqual(doc["settings"]["instruction"], INSTRUCTION)

    def test_04_style_without_template_and_template_without_style_choice(self):
        plain = self.generate("", style="cinematic", template=None)["edl"]
        self.assertIsNone(plain["template"])
        self.assertEqual([t for t in plain["titles"]], [])
        self.assertEqual(plain["transition"]["type"], "fade")
        withtpl = self.generate("", style="energetic", template="product_showcase")["edl"]
        self.assertEqual([s["name"] for s in withtpl["template"]["sections"]][0], "Hook")
        self.assertEqual(withtpl["transition"]["type"], "fadewhite")
        again = self.generate("", style="documentary", template="product_showcase")["edl"]
        self.assertEqual([s["name"] for s in again["template"]["sections"]], [s["name"] for s in withtpl["template"]["sections"]])
        self.assertEqual(again["look"], "faded")

    def test_05_new_styles_render_distinct_looks(self):
        looks = {}
        for style in ("energetic", "minimal", "documentary"):
            looks[style] = self.generate("", style=style, template=None)["edl"]
        self.assertEqual(looks["energetic"]["look"], "vivid")
        self.assertEqual(looks["minimal"]["look"], "none")
        self.assertEqual(looks["documentary"]["look"], "faded")
        self.assertEqual(looks["energetic"]["captionStyle"]["preset"], "dynamic")

    def test_06_three_music_recommendations_with_reasons(self):
        self.generate(INSTRUCTION)
        r = self.client.get(f"/api/projects/{self.pid}/music-recommendations")
        self.assertEqual(r.status_code, 200, r.text)
        tracks = r.json()["tracks"]
        self.assertEqual(len(tracks), 3)
        self.assertEqual(len({t["id"] for t in tracks}), 3)
        self.assertEqual([t["score"] for t in tracks], sorted((t["score"] for t in tracks), reverse=True))
        for t in tracks:
            self.assertTrue(music_library.is_library_id(t["id"]))
            self.assertGreater(len(t["reason"]), 10)
            self.assertTrue(t["url"].startswith("/music-library/"))
            self.assertIn("CC BY", t["attribution"])
        self.assertEqual(tracks[0]["mood"], "energetic", f"the 'upbeat' request ranks the energetic track first: {[(t['id'], t['score'], t['reason']) for t in tracks]} stored={self.client.get(f'/api/projects/{self.pid}').json()['doc']['settings']}")
        self.assertEqual(self.client.get(tracks[0]["url"]).status_code, 200, "preview audio is served")

    def test_07_target_that_cannot_fit_every_video_is_reported_not_hidden(self):
        res = self.generate("", style="cinematic", settings={"targetDuration": 5, "musicSource": "none", "captions": False})
        edl = res["edl"]
        self.assertEqual(set(self.seconds(edl)), set(self.names), "no video is dropped")
        self.assertIsNotNone(edl["conflict"])
        self.assertGreater(edl["conflict"]["suggested"], edl["conflict"]["requested"])
        self.assertIn("too short", edl["conflict"]["message"])

    def test_08_no_instruction_means_no_plan(self):
        edl = self.generate("", style="vlog", template=None, settings={"targetDuration": None})["edl"]
        self.assertIsNone(edl.get("plan"))


if __name__ == "__main__":
    unittest.main()
