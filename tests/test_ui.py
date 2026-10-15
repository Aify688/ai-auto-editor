"""Headless UI checks with Streamlit's AppTest (hermetic: projects go to a temp dir)."""
import sys
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from video_editor import workspace  # noqa: E402


def app() -> AppTest:
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)


class UI(unittest.TestCase):
    def setUp(self):
        self._old = workspace.PROJECTS_DIR
        workspace.PROJECTS_DIR = Path(tempfile.mkdtemp())

    def tearDown(self):
        workspace.PROJECTS_DIR = self._old

    def test_workspace_layout_controls(self):
        at = app().run()
        self.assertFalse(at.exception)
        labels = [b.label for b in at.button]
        # tool rail, five styles, generate, export, undo/redo toggles, app menu
        for want in ("Media", "AI Edit", "Audio", "Text", "Captions", "Effects", "Templates",
                     "Dynamic", "Cinematic", "Vlog", "Shorts", "Promotional", "Generate AI Video", "Export",
                     "Dashboard", "My Projects", "Settings"):
            self.assertIn(want, labels)
        toggles = " ".join(t.label for t in at.toggle)
        for want in ("Auto cut", "Subtitles", "Background music", "Smart transitions", "Silence removal"):
            self.assertIn(want, toggles)
        # the old Create Video / Editor entries are gone
        self.assertNotIn("Create Video", labels)
        self.assertNotIn("Editor", labels)

    def test_secondary_pages_render_with_home_navigation(self):
        for page in ("dashboard", "projects", "settings"):
            at = app()
            at.session_state.page = page
            at.run()
            self.assertFalse(at.exception, page)
            self.assertIn("Workspace", [b.label for b in at.button], page)

    def test_legacy_page_names_open_the_workspace(self):
        for legacy in ("create", "editor"):
            at = app()
            at.session_state.page = legacy
            at.run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state.page, "workspace")

    def test_style_selection_sets_switches_and_aspect(self):
        at = app().run()
        [b for b in at.button if b.key == "style_cinematic"][0].click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state.preset, "cinematic")
        self.assertFalse(at.session_state["ai_sw_subtitles"])
        self.assertTrue(at.session_state["ai_sw_transitions"])
        at = app().run()
        [b for b in at.button if b.key == "style_shorts"][0].click().run()
        self.assertEqual(at.session_state.project.export["aspect"], "9:16")

    def test_generate_disabled_without_media(self):
        at = app().run()
        gen = [b for b in at.button if b.key == "generate"][0]
        self.assertTrue(gen.disabled)
        self.assertTrue(at.button(key="export_btn").disabled)


if __name__ == "__main__":
    unittest.main()
