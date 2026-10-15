"""My Projects page: data helpers, safe destructive operations, and the page itself (temp data only)."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from video_editor import engine, library, workspace  # noqa: E402

SAMPLE = ROOT / "sample_videos" / "speech_pauses.mp4"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.out, self.proj = self.tmp / "outputs", self.tmp / "projects"
        self.out.mkdir()
        self.proj.mkdir()
        self._old = (engine.OUTPUTS_DIR, workspace.PROJECTS_DIR)
        engine.OUTPUTS_DIR, workspace.PROJECTS_DIR = self.out, self.proj

    def tearDown(self):
        engine.OUTPUTS_DIR, workspace.PROJECTS_DIR = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def video(self, name: str, plan: dict | None = None) -> Path:
        p = self.out / name
        shutil.copy(SAMPLE, p)
        if plan is not None:
            p.with_suffix(".plan.json").write_text(json.dumps(plan))
        p.with_suffix(".edl").write_text("EDL")
        return p

    def project(self, name: str, **kw) -> workspace.Project:
        p = workspace.Project(name)
        i = p.add_source(SAMPLE)
        p.append_clip(i, 8.0)
        for k, v in kw.items():
            setattr(p, k, v)
        p.save()
        return p


class Library(Base):
    def test_titles_and_ordering(self):
        a = self.video("a.mp4", {"mode": "editor", "goal": "Holiday Intro", "project_id": "x1"})
        b = self.video("b.mp4", {"preset": "shorts"})
        self.video("c.mp4")
        titles = {v.path.name: v.title for v in library.list_videos()}
        self.assertEqual(titles, {"a.mp4": "Holiday Intro", "b.mp4": "Shorts", "c.mp4": "Custom edit"})
        self.assertEqual(library.completed_project_ids(), {"x1"})
        library.rename_video(b, "My Short")
        self.assertEqual({v.path.name: v.title for v in library.list_videos()}["b.mp4"], "My Short")
        with self.assertRaises(ValueError):
            library.rename_video(b, "   ")

    def test_delete_removes_video_and_sidecars_only(self):
        a = self.video("a.mp4", {"preset": "vlog"})
        keep = self.video("keep.mp4", {"preset": "vlog"})
        removed = library.delete_video(a)
        self.assertEqual(set(removed), {"a.mp4", "a.plan.json", "a.edl"})
        self.assertTrue(keep.exists() and keep.with_suffix(".plan.json").exists())

    def test_delete_refuses_paths_outside_outputs(self):
        outside = self.tmp / "precious.mp4"
        outside.write_bytes(b"x")
        with self.assertRaises(ValueError):
            library.delete_video(outside)
        self.assertTrue(outside.exists())
        with self.assertRaises(ValueError):
            library.delete_video(self.out / ".." / "precious.mp4")


class ProjectOps(Base):
    def test_status_rules(self):
        draft = self.project("Draft one")
        self.assertEqual(draft.status(), "Draft")
        prog = self.project("Edited", preset="shorts")
        self.assertEqual(prog.status(), "In progress")
        self.assertEqual(prog.status({prog.id}), "Completed")

    def test_duplicate_rename_delete(self):
        p = self.project("Original")
        path = self.proj / f"{p.id}.json"
        dup = workspace.Project.duplicate_file(path)
        self.assertNotEqual(dup.id, p.id)
        self.assertEqual(dup.name, "Original copy")
        self.assertEqual(len(workspace.Project.list_saved()), 2)
        workspace.Project.rename_file(path, "Renamed")
        self.assertEqual(workspace.Project.load(path).name, "Renamed")
        self.assertEqual(workspace.Project.load(path).id, p.id)
        workspace.Project.delete_file(path)
        self.assertEqual(len(workspace.Project.list_saved()), 1)
        self.assertTrue(SAMPLE.exists(), "deleting a project must not touch its media")

    def test_delete_file_rejects_other_files(self):
        other = self.tmp / "x.json"
        other.write_text("{}")
        with self.assertRaises(ValueError):
            workspace.Project.delete_file(other)

    def test_export_links_back_to_project(self):
        p = self.project("Linked")
        self.assertEqual(p.to_plan()["project_id"], p.id)


class Page(Base):
    def run_page(self) -> AppTest:
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
        at.session_state.page = "projects"
        return at.run()

    def test_empty_states(self):
        at = self.run_page()
        self.assertFalse(at.exception)
        text = " ".join(m.value for m in at.markdown)
        self.assertIn("No projects yet", text)
        self.assertIn("No rendered videos yet", text)

    def test_cards_search_filter_sort(self):
        self.project("Beach Trip", preset="vlog")
        self.project("Alpha Draft")
        self.video("v1.mp4", {"preset": "shorts"})
        self.video("v2.mp4", {"mode": "editor", "goal": "Holiday Intro"})
        at = self.run_page()
        self.assertFalse(at.exception)
        labels = [b.label for b in at.button]
        self.assertEqual(labels.count("Open in editor"), 2)
        self.assertEqual(labels.count("Preview"), 2)
        self.assertIn("New Project", labels)
        html = " ".join(m.value for m in at.markdown)
        self.assertIn("Beach Trip", html)
        self.assertIn("Holiday Intro", html)

        at.text_input(key="pj_q").set_value("holiday").run()           # case-insensitive, hits videos only
        html = " ".join(m.value for m in at.markdown)
        self.assertNotIn("Beach Trip", html)
        self.assertIn("Holiday Intro", html)
        self.assertIn("No matching projects found.", html)

        at.text_input(key="pj_q").set_value("").run()
        at.selectbox(key="pj_filter").set_value("Draft").run()
        html = " ".join(m.value for m in at.markdown)
        self.assertIn("Alpha Draft", html)
        self.assertNotIn("Beach Trip", html)

        at.selectbox(key="pj_filter").set_value("All projects").run()
        at.selectbox(key="pj_sort").set_value("Name A–Z").run()
        html = " ".join(m.value for m in at.markdown)
        self.assertLess(html.index("Alpha Draft"), html.index("Beach Trip"))

    def test_open_in_editor_loads_the_project(self):
        p = self.project("Open me", preset="shorts")
        at = self.run_page()
        [b for b in at.button if b.key == f"open_{p.id}"][0].click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state.page, "workspace")
        self.assertEqual(at.session_state.project.id, p.id)

    def test_new_project_button_starts_fresh_workspace(self):
        self.project("Existing")
        at = self.run_page()
        at.button(key="pj_new").click().run()
        self.assertEqual(at.session_state.page, "workspace")
        self.assertEqual(at.session_state.project.name, "Untitled project")

    def test_nav_active_tab_and_links(self):
        at = self.run_page()
        types = {b.label: b.proto.type for b in at.button if b.key and b.key.startswith("nav_")}
        self.assertEqual(types["My Projects"], "primary")
        self.assertEqual(types["Dashboard"], "secondary")
        at.button(key="nav_settings").click().run()
        self.assertEqual(at.session_state.page, "settings")
        self.assertFalse(at.exception)


if __name__ == "__main__":
    unittest.main()
