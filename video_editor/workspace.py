"""Editor project model: timeline segments + skill settings + undo/redo + persistence.

Pure Python (no Streamlit). The timeline UI edits `segments`/`cues`; the property
panels edit `skills`/`export`. `to_plan()` turns the project into the same
structured plan the engine validates and renders.
"""
from __future__ import annotations

import copy
import json
import re
import time
import uuid
from pathlib import Path

from . import planning, registry, validate

PROJECTS_DIR = Path(__file__).resolve().parent.parent / "projects"
HISTORY_LIMIT = 100


def _new_id() -> str:
    return "s" + uuid.uuid4().hex[:6]


class Project:
    def __init__(self, name: str = "Untitled project"):
        self.id = uuid.uuid4().hex[:10]
        self.name = name
        self.sources: list[str] = []           # absolute paths, index = clip number
        self.segments: list[dict] = []         # {id, clip, start, end, break?}
        self.skills: dict[str, dict] = {}      # capability id -> settings
        self.export: dict = dict(validate.DEFAULT_EXPORT)
        self.cues: list[dict] = []             # {id, clip, start, end, text}
        self.notes: list[str] = []
        self.preset: str | None = None         # last style used by Generate AI Video
        self.version = 0                       # bumps on every change (UI re-sync key)
        self._undo: list[str] = []
        self._redo: list[str] = []

    # ------------------------------------------------------------ history
    def _state(self) -> dict:
        return {"name": self.name, "sources": self.sources, "segments": self.segments, "skills": self.skills,
                "export": self.export, "cues": self.cues}

    def _push(self) -> None:
        self._undo.append(json.dumps(self._state()))
        del self._undo[:-HISTORY_LIMIT]
        self._redo.clear()
        self.version += 1

    def _restore(self, blob: str) -> None:
        s = json.loads(blob)
        self.name, self.sources, self.segments = s["name"], s["sources"], s["segments"]
        self.skills, self.export, self.cues = s["skills"], s["export"], s["cues"]
        self.version += 1

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(json.dumps(self._state()))
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(json.dumps(self._state()))
        self._restore(self._redo.pop())
        return True

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    # ------------------------------------------------------------ media / timeline
    def add_source(self, path: str | Path) -> int:
        p = str(Path(path).resolve())
        if p in self.sources:
            return self.sources.index(p)
        self.sources.append(p)
        self.version += 1
        return len(self.sources) - 1

    def append_clip(self, clip: int, duration: float) -> None:
        self._push()
        self.segments.append({"id": _new_id(), "clip": clip, "start": 0.0, "end": round(duration, 3)})

    def set_segments(self, segs: list[dict], durations: dict[int, float]) -> list[str]:
        """Replace the timeline from the UI. Returns problems; nothing changes if any."""
        out, problems = [], []
        for s in segs:
            try:
                clip, a, b = int(s["clip"]), float(s["start"]), float(s["end"])
            except (KeyError, TypeError, ValueError):
                problems.append("malformed segment")
                continue
            if clip not in durations:
                problems.append(f"unknown clip {clip}")
                continue
            a, b = max(0.0, a), min(b, durations[clip])
            if b - a < validate.MIN_SEGMENT:
                problems.append("segment shorter than 0.2s")
                continue
            seg = {"id": str(s.get("id") or _new_id()), "clip": clip, "start": round(a, 3), "end": round(b, 3)}
            if s.get("break"):
                seg["break"] = True
            out.append(seg)
        if problems:
            return problems
        if out != self.segments:
            self._push()
            self.segments = out
        return []

    def set_cues(self, cues: list[dict]) -> None:
        clean = []
        for c in cues:
            try:
                clean.append({"id": str(c.get("id") or _new_id()), "clip": int(c.get("clip", 0)),
                              "start": round(float(c["start"]), 3), "end": round(float(c["end"]), 3),
                              "text": str(c["text"]).strip()})
            except (KeyError, TypeError, ValueError):
                continue
        if clean != self.cues:
            self._push()
            self.cues = clean

    def update_cue_text(self, cue_id: str, text: str) -> None:
        for c in self.cues:
            if c["id"] == cue_id and c["text"] != text:
                self._push()
                c["text"] = text.strip()
                return

    # ------------------------------------------------------------ skills / export
    def set_skill(self, skill_id: str, settings: dict | None) -> None:
        """Enable/update a skill (settings dict) or remove it (None)."""
        if settings is None:
            if skill_id in self.skills:
                self._push()
                del self.skills[skill_id]
            return
        if self.skills.get(skill_id) != settings:
            self._push()
            self.skills[skill_id] = dict(settings)

    def set_export(self, **kw) -> None:
        new = {**self.export, **kw}
        if new != self.export:
            self._push()
            self.export = new

    # ------------------------------------------------------------ plan
    def to_plan(self) -> dict:
        skills = []
        for sid, st in self.skills.items():
            if sid == "captions.burn":
                if not self.cues:
                    continue
                st = {**st, "cues": [{k: c[k] for k in ("clip", "start", "end", "text")} for c in self.cues]}
            skills.append({"id": sid, "settings": st})
        return {"version": 1, "goal": self.name, "mode": "editor", "project_id": self.id,
                "sources": [{"path": p} for p in self.sources],
                "segments": [{k: v for k, v in s.items() if k != "id"} for s in self.segments],
                "skills": skills, "export": self.export, "rationale": list(self.notes)}

    def apply_plan(self, plan: dict, notes: list[str] | None = None) -> None:
        """Load an AI-generated plan onto the timeline (one undo step)."""
        self._push()
        self.segments = [{"id": _new_id(), **s} for s in plan["segments"]]
        self.skills, self.cues = {}, []
        for e in plan["skills"]:
            if e["id"] in ("captions.transcribe",) or registry.get(e["id"]).stage == "analyze":
                continue
            st = dict(e["settings"])
            if e["id"] == "captions.burn":
                self.cues = [{"id": _new_id(), **c} for c in st.pop("cues", [])]
            self.skills[e["id"]] = st
        self.export = {**self.export, **{k: v for k, v in plan["export"].items()}}
        self.notes = list(notes if notes is not None else plan.get("rationale", []))

    # ------------------------------------------------------------ persistence
    def save(self) -> Path:
        PROJECTS_DIR.mkdir(exist_ok=True)
        path = PROJECTS_DIR / f"{self.id}.json"
        path.write_text(json.dumps({**self._state(), "id": self.id, "saved": time.time(),
                                    "notes": self.notes, "preset": self.preset}, indent=1))
        return path

    @classmethod
    def load(cls, path: Path) -> "Project":
        d = json.loads(Path(path).read_text())
        p = cls(d.get("name", "Untitled project"))
        p.id = d.get("id", p.id)
        p.sources, p.segments, p.skills = d["sources"], d["segments"], d["skills"]
        p.export = {**validate.DEFAULT_EXPORT, **d.get("export", {})}
        p.cues, p.notes = d.get("cues", []), d.get("notes", [])
        p.preset = d.get("preset")
        return p

    @staticmethod
    def delete_file(path: Path) -> None:
        """Remove only the project document; imported media and renders are left untouched."""
        path = Path(path).resolve()
        if path.parent != PROJECTS_DIR.resolve() or path.suffix != ".json":
            raise ValueError("Not a project file.")
        path.unlink()

    @classmethod
    def duplicate_file(cls, path: Path) -> "Project":
        p = cls.load(path)
        p.id = uuid.uuid4().hex[:10]
        p.name = f"{p.name} copy"
        p.save()
        return p

    @classmethod
    def rename_file(cls, path: Path, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("The name can't be empty.")
        p = cls.load(path)
        p.name = name[:120]
        p.id = Path(path).stem
        p.save()

    def status(self, completed_ids: set | None = None) -> str:
        """Draft: imported but never edited. In progress: has an edit. Completed: an export is linked."""
        if completed_ids and self.id in completed_ids:
            return "Completed"
        edited = bool(self.preset or self.skills or self.cues or self.notes
                      or len(self.segments) > max(1, len(self.sources)))
        return "In progress" if edited else "Draft"

    @staticmethod
    def list_saved() -> list[Path]:
        PROJECTS_DIR.mkdir(exist_ok=True)
        return sorted(PROJECTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    # ------------------------------------------------------------ geometry helpers
    def speed(self) -> float:
        return float(self.skills.get("time.speed", {}).get("factor", 1.0))

    def timeline_length(self) -> float:
        sp = self.speed()
        return sum((s["end"] - s["start"]) / sp for s in self.segments)


# ---------------------------------------------------------------- AI Auto Edit
AUTO_OPTIONS = ("silence", "cut_scenes", "highlights", "subtitles", "transitions", "music")


def auto_edit(project: Project, opts: dict, caption_files: dict | None = None, music_path: str | None = None,
              whisper_model: str = "base", progress=None) -> dict:
    """Run the analysis skills for the chosen options and load the result onto the timeline.

    opts: silence, cut_scenes (+keep_pct), highlights (+highlight_seconds), subtitles, transitions, music.
    Returns {"notes": [...], "unsupported": [...]}.
    """
    paths = [Path(p) for p in project.sources]
    if not paths:
        raise ValueError("Import a video first.")
    clips = planning._probe(paths)
    total = sum(c.duration for c in clips)
    sel = planning.Selection(caption_files=dict(caption_files or {}))
    sel.export = {k: v for k, v in project.export.items() if k in ("aspect", "fit", "short_edge", "fps", "crf")}
    sk = sel.skills
    if opts.get("silence"):
        sk["cut.remove_pauses"] = {}
    if opts.get("highlights"):
        tgt = float(opts.get("highlight_seconds", 30))
        if total > tgt + 0.5:
            sk["story.best_moments"] = {"target_duration": tgt, "window": 3.0, "hook_first": True}
        else:
            sel.notes.append("Highlights: footage is already shorter than the highlight length.")
    elif opts.get("cut_scenes"):
        tgt = max(5.0, total * float(opts.get("keep_pct", 70)) / 100.0)
        if total > tgt + 0.5:
            sk["story.best_moments"] = {"target_duration": tgt, "window": 4.0, "hook_first": False}
    if opts.get("subtitles"):
        sk["captions.burn"] = {}
        if not sel.caption_files:
            if registry.get("captions.transcribe").available:
                sk["captions.transcribe"] = {"model": whisper_model}
            else:
                sk.pop("captions.burn")
                sel.unsupported.append("Subtitles: needs an SRT/VTT file or "
                                       + registry.get("captions.transcribe").status()[1])
    if opts.get("transitions"):
        sk["transition.crossfade"] = {"type": opts.get("transition_type", "fade"), "duration": 0.5}
    if opts.get("music"):
        if music_path:
            sk["audio.music_bed"] = {"path": music_path, "volume": 0.2, "duck": True}
        else:
            sel.unsupported.append("Background music: choose a music file first.")
    # keep what the user already tuned
    for keep in ("audio.loudnorm", "audio.clean", "color.look", "color.adjust"):
        if keep in project.skills:
            sk.setdefault(keep, project.skills[keep])
    plan = planning.build_plan(paths, sel, "AI Auto Edit", "auto", progress=progress)
    project.apply_plan(plan, notes=plan["rationale"])
    return {"notes": plan["rationale"], "unsupported": sel.unsupported}


# ---------------------------------------------------------------- Generate AI Video (style + switches -> timeline)
def generation_steps(switches: dict) -> list[tuple[str, str]]:
    """(event key, label) for the steps a generation will actually perform."""
    steps = [("analyze", "Analyzing footage")]
    if switches.get("autocut"):
        steps.append(("story.best_moments", "Picking best moments"))
    if switches.get("silence"):
        steps.append(("cut.remove_pauses", "Removing silence"))
    if switches.get("subtitles"):
        steps.append(("captions.transcribe", "Preparing subtitles"))
    steps.append(("timeline", "Building timeline"))
    return steps


def generate_from_preset(project: Project, preset_key: str, switches: dict, *, target: float | None = None,
                         hook: bool | None = None, caption_files: dict | None = None, music_path: str | None = None,
                         look: str | None = None, whisper_model: str = "base", progress=None) -> dict:
    """Run a style preset + the five switches and load the result onto the project timeline.

    Same selection logic as the quick-create presets (video_editor.presets), but the output is
    editable timeline segments instead of a rendered file. Returns {"notes", "unsupported"}.
    """
    from . import presets as _presets

    paths = [Path(p) for p in project.sources]
    if not paths:
        raise ValueError("Import a video first.")
    clips = planning._probe(paths)
    total = sum(c.duration for c in clips)
    keep_export = {k: v for k, v in project.export.items() if k in ("aspect", "fit", "short_edge", "fps", "crf")}
    sel = _presets.build_selection(preset_key, switches, total=total, target=target, caption_files=caption_files,
                                   music_path=music_path, whisper_model=whisper_model,
                                   short_edge=keep_export.get("short_edge", 1080), overrides=keep_export)
    if hook is not None and "story.best_moments" in sel.skills:
        sel.skills["story.best_moments"]["hook_first"] = bool(hook)
    if look:
        sel.skills["color.look"] = {"look": look}
    if progress:
        progress("analyze")
    plan = planning.build_plan(paths, sel, preset_key, "auto", progress=progress)
    plan["preset"] = preset_key
    project.apply_plan(plan, notes=plan["rationale"])
    project.preset = preset_key
    if progress:
        progress("timeline")
    return {"notes": plan["rationale"], "unsupported": sel.unsupported}
