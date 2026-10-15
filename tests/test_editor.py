"""End-to-end verification against real sample videos (run: python -m unittest -v)."""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from video_editor import ffmpeg_ops, planning, registry, validate
from video_editor.engine import execute_plan

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "sample_videos"
A = SAMPLES / "speech_pauses.mp4"      # 8 s, pauses at 1.5-3.0, 4.5-5.2, 6.5-7.0
B = SAMPLES / "second_clip.mp4"        # 5 s
SRT = (SAMPLES / "speech_pauses.srt").read_text()


def frame(path: Path, t: float, size=None) -> np.ndarray:
    info = ffmpeg_ops.probe_video(path)
    w, h = size or (info.width, info.height)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(float)


def lufs(path: Path) -> float:
    r = subprocess.run(["ffmpeg", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)[-1])


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def render(self, sel, paths=(A,), goal="", **kw):
        plan = planning.build_plan(list(paths), sel, goal)
        return execute_plan(plan, out_dir=self.out), plan


class Stage1CoreFlow(Base):
    """upload -> remove pauses -> subtitles -> resize -> preview -> export"""

    def test_full_flow(self):
        sel = planning.Selection(
            skills={"cut.remove_pauses": {}, "captions.burn": {}},
            export={"aspect": "9:16"}, caption_files={0: SRT})
        res, plan = self.render(sel)
        info = ffmpeg_ops.probe_video(res.output)
        self.assertEqual((info.width, info.height), (1080, 1920))
        self.assertTrue(info.has_audio)
        # 3 pauses (1.5 + 0.7 + 0.5 = 2.7 s) minus 0.12 s padding per side kept
        self.assertLess(info.duration, 8 - 1.5)
        self.assertGreater(info.duration, 4.0)
        self.assertGreaterEqual(len(plan["segments"]), 3)
        self.assertTrue(res.edl_path.exists() and res.plan_path.exists())

    def test_captions_visible_and_remapped(self):
        base = planning.Selection(skills={"cut.remove_pauses": {}}, export={"aspect": "9:16"})
        cap = planning.Selection(skills={"cut.remove_pauses": {}, "captions.burn": {}},
                                 export={"aspect": "9:16"}, caption_files={0: SRT})
        r0, _ = self.render(base)
        r1, _ = self.render(cap)
        t = 0.6  # inside the first caption after remap
        diff = np.abs(frame(r1.output, t) - frame(r0.output, t)).sum(axis=2)
        ys, _ = np.nonzero(diff > 60)
        self.assertGreater(len(ys), 500, "caption pixels expected")
        # caption sits above the bottom 20% safe zone on 9:16
        self.assertLess(ys.max(), 1920 * 0.9)
        self.assertGreater(ys.min(), 1920 * 0.55)

    def test_no_pause_left_in_output(self):
        res, _ = self.render(planning.Selection(skills={"cut.remove_pauses": {"padding": 0.05}}))
        from video_editor import analysis
        left = [(a, b) for a, b in analysis.detect_silences(res.output, -30, 0.5)]
        self.assertEqual(left, [], f"silence >0.5s remains: {left}")


class Stage2Audio(Base):
    def test_loudnorm_hits_target(self):
        res, _ = self.render(planning.Selection(skills={"audio.loudnorm": {"target_lufs": -16.0}}))
        self.assertAlmostEqual(lufs(res.output), -16.0, delta=1.5)

    def test_music_bed_mixed(self):
        music = self.out / "music.wav"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=2", str(music)],
                       capture_output=True, check=True)
        sel = planning.Selection(skills={"audio.music_bed": {"path": str(music), "volume": 0.5, "duck": True}})
        res, _ = self.render(sel)
        # gap 1.5-3.0 has no voice, so music alone should be audible there
        r = subprocess.run(["ffmpeg", "-nostats", "-ss", "1.7", "-t", "1.0", "-i", str(res.output),
                            "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
        mean = float(re.search(r"mean_volume: (-?[\d.]+)", r.stderr).group(1))
        self.assertGreater(mean, -50, "music should be audible in the pause")
        self.assertAlmostEqual(res.duration, 8.0, delta=0.3)


class Stage3Color(Base):
    def test_look_changes_pixels(self):
        r0, _ = self.render(planning.Selection())
        r1, _ = self.render(planning.Selection(skills={"color.look": {"look": "bw"}}))
        f1 = frame(r1.output, 1.0)
        chroma = np.abs(f1[..., 0] - f1[..., 1]).mean() + np.abs(f1[..., 1] - f1[..., 2]).mean()
        f0 = frame(r0.output, 1.0)
        chroma0 = np.abs(f0[..., 0] - f0[..., 1]).mean() + np.abs(f0[..., 1] - f0[..., 2]).mean()
        self.assertLess(chroma, chroma0 * 0.2)

    def test_brightness_adjust(self):
        r0, _ = self.render(planning.Selection())
        r1, _ = self.render(planning.Selection(skills={"color.adjust": {"brightness": 0.2}}))
        self.assertGreater(frame(r1.output, 1.0).mean(), frame(r0.output, 1.0).mean() + 10)


class Stage4TransitionsAndTime(Base):
    def test_crossfade_duration(self):
        sel = planning.Selection(skills={"transition.crossfade": {"type": "fade", "duration": 1.0}})
        res, plan = self.render(sel, paths=(A, B))
        self.assertAlmostEqual(res.duration, 8 + 5 - 1.0, delta=0.3)
        self.assertEqual(len(res.timeline), 2)
        self.assertAlmostEqual(res.timeline[1]["out_start"], 7.0, delta=0.3)

    def test_speed(self):
        res, _ = self.render(planning.Selection(skills={"time.speed": {"factor": 2.0}}))
        self.assertAlmostEqual(res.duration, 4.0, delta=0.3)

    def test_best_moments_hits_target(self):
        sel = planning.Selection(skills={"story.best_moments": {"target_duration": 6.0, "window": 2.0,
                                                                "hook_first": True}})
        res, plan = self.render(sel, paths=(A, B))
        self.assertAlmostEqual(res.duration, 6.0, delta=0.6)


class Stage5Graphics(Base):
    def test_title_and_lower_third(self):
        r0, _ = self.render(planning.Selection())
        sel = planning.Selection(skills={"graphics.title": {"text": "Hello world", "start": 0.0, "duration": 2.0}})
        r1, _ = self.render(sel)
        diff = np.abs(frame(r1.output, 1.0) - frame(r0.output, 1.0)).sum(axis=2)
        self.assertGreater((diff > 60).sum(), 500)
        # encoder noise on the moving test pattern is ignored: look only at the title band
        band = lambda a: a[400:700]
        after = np.abs(frame(r1.output, 4.0) - frame(r0.output, 4.0)).sum(axis=2)
        during = diff
        self.assertGreater((band(during) > 60).sum(), 3000)
        self.assertLess((band(after) > 60).sum(), (band(during) > 60).sum() * 0.02,
                        "title must disappear after its duration")


class Registry(unittest.TestCase):
    def test_every_entry_has_status_and_reason(self):
        for cap in registry.CAPS:
            status, reason = cap.status()
            if status != registry.AVAILABLE:
                self.assertTrue(reason, cap.id)

    def test_available_means_handler_resolves(self):
        for cap in registry.CAPS:
            if cap.available:
                self.assertIsNotNone(cap.resolve_handler(), cap.id)

    def test_known_unavailable(self):
        st, reason = registry.get("captions.transcribe").status()
        if st != registry.AVAILABLE:
            self.assertEqual(st, registry.MISSING_DEP)
            self.assertIn("faster-whisper", reason)
        self.assertEqual(registry.get("ext.ai_masking").status()[0], registry.EXTERNAL)
        self.assertEqual(registry.get("cut.jl_cuts").status()[0], registry.NOT_IMPLEMENTED)


class Validation(Base):
    def base(self):
        return {"sources": [{"path": str(A)}], "segments": [{"clip": 0, "start": 0, "end": 3}], "skills": []}

    def test_rejects_bad_timestamps(self):
        p = self.base()
        p["segments"] = [{"clip": 0, "start": 9.0, "end": 12.0}, {"clip": 3, "start": 0, "end": 1}]
        v = validate.validate_plan(p)
        self.assertFalse(v.ok)
        self.assertTrue(any("beyond clip length" in e for e in v.errors))
        self.assertTrue(any("clip 3" in e for e in v.errors))

    def test_rejects_unavailable_and_unknown_skill(self):
        p = self.base()
        p["skills"] = [{"id": "ext.ai_masking"}, {"id": "nope.nope"}, {"id": "fx.stabilize"}]
        v = validate.validate_plan(p)
        self.assertEqual(len([e for e in v.errors if "unavailable" in e or "unknown" in e or "not an" in e]), 3)

    def test_rejects_bad_settings_and_blocks_execution(self):
        p = self.base()
        p["skills"] = [{"id": "audio.loudnorm", "settings": {"target_lufs": 5}}]
        with self.assertRaises(validate.PlanError):
            execute_plan(p, out_dir=self.out)

    def test_transition_too_long(self):
        p = self.base()
        p["sources"].append({"path": str(B)})
        p["segments"] = [{"clip": 0, "start": 0, "end": 1}, {"clip": 1, "start": 0, "end": 1}]
        p["skills"] = [{"id": "transition.crossfade", "settings": {"duration": 1.0}}]
        self.assertFalse(validate.validate_plan(p).ok)


class Modes(Base):
    def test_auto_from_goal(self):
        plan, sel = planning.auto_plan([A], "Make a TikTok of this, remove the pauses and add captions",
                                       caption_files={0: SRT})
        ids = {s["id"] for s in plan["skills"]}
        self.assertTrue({"cut.remove_pauses", "captions.burn", "audio.loudnorm"} <= ids)
        self.assertEqual(plan["export"]["aspect"], "9:16")
        self.assertTrue(validate.validate_plan(plan).ok)

    def test_auto_without_captions_source_explains(self):
        plan, sel = planning.auto_plan([A], "vertical video with captions")
        if not registry.get("captions.transcribe").available:
            self.assertNotIn("captions.burn", {s["id"] for s in plan["skills"]})
            self.assertTrue(any("Upload an SRT" in u for u in sel.unsupported))

    def test_chat_is_incremental_and_honest(self):
        chat = planning.ChatSession([A], caption_files={0: SRT})
        t1 = chat.send("remove the pauses")
        t2 = chat.send("make it vertical and add subtitles")
        t3 = chat.send("stabilize it and add a cinematic look")
        self.assertIn("cut.remove_pauses", {s["id"] for s in t2.plan["skills"]})
        self.assertEqual(t2.plan["export"]["aspect"], "9:16")
        self.assertIn("Could not do", t3.reply)
        self.assertIn("libvidstab", t3.reply)
        self.assertIn("color.look", {s["id"] for s in t3.plan["skills"]})
        res = execute_plan(t3.plan, out_dir=self.out)
        self.assertTrue(res.output.exists())

    def test_llm_path_rejects_unavailable_skill(self):
        fake = lambda prompt: json.dumps({"skills": {"audio.loudnorm": {"target_lufs": -18},
                                                     "ext.ai_masking": {}}})
        chat = planning.ChatSession([A], llm=fake)
        t = chat.send("make it sound consistent")
        self.assertIn("audio.loudnorm", {s["id"] for s in t.plan["skills"]})
        self.assertIn("unavailable skill", t.reply)


@unittest.skipUnless(registry.get("captions.transcribe").available and (SAMPLES / "speech_real.mp4").exists(),
                     "faster-whisper or speech sample missing")
class Transcription(Base):
    def test_auto_captions_from_speech(self):
        plan, _ = planning.auto_plan([SAMPLES / "speech_real.mp4"], "vertical TikTok with captions")
        cues = next(s for s in plan["skills"] if s["id"] == "captions.burn")["settings"]["cues"]
        text = " ".join(c["text"].lower() for c in cues)
        self.assertIn("demo", text)
        self.assertTrue(execute_plan(plan, out_dir=self.out).output.exists())


class LegacyPreserved(unittest.TestCase):
    def test_old_pipeline_still_works(self):
        from video_editor import pipeline
        old = pipeline.OUTPUTS_DIR
        with tempfile.TemporaryDirectory() as d:
            pipeline.OUTPUTS_DIR = Path(d)
            try:
                out = pipeline.process_videos([A, B], 6.0, "1:1 (Square, 1080x1080)")
                info = ffmpeg_ops.probe_video(out)
                self.assertEqual((info.width, info.height), (1080, 1080))
            finally:
                pipeline.OUTPUTS_DIR = old


if __name__ == "__main__":
    unittest.main()


class PresetFlow(Base):
    """UI presets -> real renders (the exact path the Generate button uses)."""
    SW = {"autocut": False, "subtitles": False, "music": False, "transitions": False, "silence": True}

    def gen(self, preset, switches, paths=(A,), **kw):
        from video_editor import presets
        events = []
        res, sel = presets.generate(list(paths), preset, switches, target=kw.get("target"),
                                    caption_files=kw.get("captions"), music_path=kw.get("music"),
                                    whisper_model="base", short_edge=720,
                                    on_progress=lambda k, f: events.append((k, f)), out_dir=self.out)
        return res, sel, events

    def test_shorts_with_srt(self):
        res, sel, events = self.gen("shorts", {**self.SW, "subtitles": True}, captions={0: SRT})
        info = ffmpeg_ops.probe_video(res.output)
        self.assertEqual((info.width, info.height), (720, 1280))
        ids = {s["id"] for s in res.plan["skills"]}
        self.assertTrue({"captions.burn", "cut.remove_pauses", "audio.loudnorm"} <= ids)
        fracs = [f for _, f in events]
        self.assertEqual(fracs, sorted(fracs))
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(res.plan["preset"], "shorts")

    def test_promo_autocut_with_transitions_between_moments(self):
        sw = {**self.SW, "autocut": True, "transitions": True}
        res, sel, _ = self.gen("promo", sw, paths=(A,), target=4.0)
        info = ffmpeg_ops.probe_video(res.output)
        self.assertEqual((info.width, info.height), (720, 720))
        self.assertTrue(any(s.get("break") for s in res.plan["segments"]), "moments should be scene breaks")
        self.assertLess(res.duration, 5.5)

    def test_cinematic_has_look_and_fades(self):
        res, _, _ = self.gen("cinematic", {**self.SW, "silence": False})
        ids = {s["id"] for s in res.plan["skills"]}
        self.assertTrue({"color.look", "audio.fades"} <= ids)

    def test_subtitles_without_source_is_reported_not_faked(self):
        from video_editor import presets, registry
        sel = presets.build_selection("shorts", {**self.SW, "subtitles": True}, total=8)
        if registry.get("captions.transcribe").available:
            self.assertIn("captions.transcribe", sel.skills)
        else:
            self.assertNotIn("captions.burn", sel.skills)
            self.assertTrue(sel.unsupported)

    def test_music_switch_requires_file(self):
        from video_editor import presets
        probs = presets.blocking_problems({"music": True}, n_clips=1, has_srt=False, music_path=None)
        self.assertTrue(probs)
        self.assertEqual(presets.blocking_problems({"music": False}, n_clips=1, has_srt=False, music_path=None), [])


class WorkspaceModel(Base):
    def setUp(self):
        from video_editor import workspace
        self.ws = workspace
        self.p = workspace.Project("t")
        self.p.add_source(A)
        self.p.append_clip(0, 8.0)
        self.durs = {0: 8.0}

    def test_edit_history_and_validation(self):
        segs = [dict(self.p.segments[0], end=3.0), {"id": "x2", "clip": 0, "start": 3.0, "end": 8.0}]
        self.assertEqual(self.p.set_segments(segs, self.durs), [])
        self.assertEqual(len(self.p.segments), 2)
        self.assertTrue(self.p.undo())
        self.assertEqual(len(self.p.segments), 1)
        self.assertTrue(self.p.redo())
        self.assertEqual(len(self.p.segments), 2)
        before = list(self.p.segments)
        self.assertTrue(self.p.set_segments([{"clip": 0, "start": 1, "end": 1.05}], self.durs))
        self.assertTrue(self.p.set_segments([{"clip": 7, "start": 1, "end": 3}], self.durs))
        self.assertEqual(self.p.segments, before, "rejected edits must not change the project")

    def test_timeline_edits_reach_the_render(self):
        self.p.set_segments([{"clip": 0, "start": 0, "end": 2}, {"clip": 0, "start": 5, "end": 7}], self.durs)
        self.p.set_skill("color.look", {"look": "bw"})
        plan = self.p.to_plan()
        self.assertEqual([(s["start"], s["end"]) for s in plan["segments"]], [(0, 2), (5, 7)])
        res = execute_plan(plan, out_dir=self.out)
        self.assertAlmostEqual(res.duration, 4.0, delta=0.3)

    def test_ai_auto_edit_loads_timeline_and_is_undoable(self):
        r = self.ws.auto_edit(self.p, {"silence": True})
        self.assertGreaterEqual(len(self.p.segments), 3)
        self.assertLess(self.p.timeline_length(), 6.5)
        self.assertTrue(self.p.undo())
        self.assertEqual(len(self.p.segments), 1)

    def test_save_load_roundtrip(self):
        import tempfile
        from pathlib import Path as P
        self.p.set_skill("audio.loudnorm", {"target_lufs": -16.0})
        old = self.ws.PROJECTS_DIR
        self.ws.PROJECTS_DIR = P(tempfile.mkdtemp())
        try:
            path = self.p.save()
            q = self.ws.Project.load(path)
        finally:
            self.ws.PROJECTS_DIR = old
        self.assertEqual(q.segments, self.p.segments)
        self.assertEqual(q.skills, self.p.skills)
        self.assertEqual(q.name, "t")

    def test_media_prep(self):
        from video_editor import media
        m = media.ingest(A)
        self.assertTrue((ROOT / "static" / "proxy" / f"{m['id']}_p540.mp4").exists())
        self.assertEqual(m["sprite"]["count"], 16)
        self.assertTrue(m["peaks"])


class GenerateOntoTimeline(Base):
    """Right-panel 'Generate AI Video': style + switches -> editable timeline (no render)."""
    SW = {"autocut": True, "subtitles": False, "music": False, "transitions": True, "silence": True}

    def project(self):
        from video_editor import workspace
        p = workspace.Project("g")
        i = p.add_source(A)
        p.append_clip(i, 8.0)
        j = p.add_source(B)
        p.append_clip(j, 5.0)
        return p

    def test_styles_produce_different_timelines(self):
        from video_editor import workspace
        out = {}
        for style in ("dynamic", "cinematic", "vlog"):
            p = self.project()
            events = []
            workspace.generate_from_preset(p, style, {**self.SW, "autocut": style == "dynamic"}, target=6.0,
                                           progress=events.append)
            out[style] = (len(p.segments), round(p.timeline_length(), 1), p.skills.get("color.look", {}).get("look"))
            self.assertEqual(events[0], "analyze")
            self.assertEqual(events[-1], "timeline")
        self.assertEqual(out["dynamic"][2], "vivid")
        self.assertEqual(out["cinematic"][2], "cinematic")
        self.assertEqual(out["vlog"][2], "warm")
        self.assertLessEqual(out["dynamic"][1], 7.5)               # auto cut hit the target
        self.assertGreater(out["cinematic"][1], out["dynamic"][1])  # no auto cut keeps more footage
        self.assertEqual(len({v for v in out.values()}), 3)

    def test_generated_timeline_renders_and_is_undoable(self):
        from video_editor import workspace
        p = self.project()
        before = [dict(s) for s in p.segments]
        workspace.generate_from_preset(p, "shorts", {**self.SW, "transitions": False}, target=6.0)
        self.assertTrue(p.undo())
        self.assertEqual(p.segments, before)
        p.redo()
        res = execute_plan(p.to_plan(), out_dir=self.out)
        self.assertAlmostEqual(res.duration, p.timeline_length(), delta=0.5)

    def test_preset_catalogue(self):
        from video_editor import presets
        self.assertEqual(list(presets.PRESETS), ["dynamic", "cinematic", "vlog", "shorts", "promo"])
