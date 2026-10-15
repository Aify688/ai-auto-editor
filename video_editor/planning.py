"""Plan construction for the three editing modes.

  Custom : explicit skill selections + settings  -> build_plan()
  Auto   : goal text -> rules + parser           -> auto_plan()
  Chat   : conversation of requests, incremental -> ChatSession
All three produce the same structured plan, which validate.py checks and
engine.py executes. Parsing is rule-based; an LLM path (llm_plan) is used only
when ANTHROPIC_API_KEY and the SDK are present.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import analysis, ffmpeg_ops, registry, skills, validate
from .skills import PlanCtx, Seg

ANALYZE_ORDER = ["story.best_moments", "cut.remove_pauses", "captions.transcribe"]

# ------------------------------------------------------------ platform rules
PLATFORMS = {
    "tiktok": {"aspect": "9:16", "lufs": -14.0, "captions": True, "max": 600, "short": True},
    "reels": {"aspect": "9:16", "lufs": -14.0, "captions": True, "max": 180, "short": True},
    "shorts": {"aspect": "9:16", "lufs": -14.0, "captions": True, "max": 180, "short": True},
    "instagram": {"aspect": "4:5", "lufs": -14.0, "captions": True, "max": 180, "short": True},
    "youtube": {"aspect": "16:9", "lufs": -14.0, "captions": False, "max": None, "short": False},
    "linkedin": {"aspect": "16:9", "lufs": -16.0, "captions": True, "max": None, "short": False},
    "podcast": {"aspect": "16:9", "lufs": -16.0, "captions": False, "max": None, "short": False},
    "broadcast": {"aspect": "16:9", "lufs": -23.0, "captions": False, "max": None, "short": False},
}
PLATFORM_ALIASES = {"tik tok": "tiktok", "reel": "reels", "instagram reel": "reels", "yt": "youtube",
                    "youtube short": "shorts", "yt short": "shorts"}


def platform_rule(goal: str) -> dict | None:
    g = goal.lower()
    for alias, key in PLATFORM_ALIASES.items():
        if alias in g:
            return {"platform": key, **PLATFORMS[key]}
    for key in PLATFORMS:
        if re.search(rf"\b{key}\b", g):
            return {"platform": key, **PLATFORMS[key]}
    return None


def pacing_rule(platform_info: dict | None) -> float:
    """Moment window (s) for best-moments selection."""
    return 3.0 if platform_info and platform_info.get("short") else 4.0


# ------------------------------------------------------------ plan building
def _probe(paths: list[Path]) -> list[ffmpeg_ops.ClipInfo]:
    return [ffmpeg_ops.probe_video(Path(p)) for p in paths]


@dataclass
class Selection:
    """User/agent intent before analysis: skills + settings + export + caption sources."""
    skills: dict[str, dict] = field(default_factory=dict)
    export: dict = field(default_factory=dict)
    caption_files: dict[int, str] = field(default_factory=dict)  # clip index -> srt text
    notes: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


def build_plan(paths: list[Path], sel: Selection, goal: str = "", mode: str = "custom",
               progress: Callable[[str], None] | None = None) -> dict:
    """Run analysis-stage skills, then assemble the structured plan."""
    clips = _probe(paths)
    ctx = PlanCtx(clips=clips, segments=[Seg(i, 0.0, c.duration) for i, c in enumerate(clips)])
    chosen = dict(sel.skills)
    rationale = list(sel.notes)

    # captions: imported files first, otherwise transcription if asked for
    for ci, text in sel.caption_files.items():
        if 0 <= ci < len(clips):
            for c in analysis.parse_srt(text):
                ctx.cues.append({"clip": ci, **c})
            rationale.append(f"Imported {len(ctx.cues)} caption cue(s) for clip {ci}.")
    for sid in ANALYZE_ORDER:
        if sid in chosen:
            if progress:
                progress(sid)
            cap = registry.get(sid)
            status, reason = cap.status()
            if status != registry.AVAILABLE:
                rationale.append(f"Skipped {cap.name}: {reason}")
                chosen.pop(sid)
                continue
            settings, errs = cap.normalize_settings(chosen[sid])
            if errs:
                raise validate.PlanError("; ".join(errs))
            cap.resolve_handler()(ctx, settings)

    out_skills = []
    for sid, st in chosen.items():
        cap = registry.get(sid)
        if cap.stage == "analyze":
            out_skills.append({"id": sid, "settings": st})
            continue
        st = dict(st)
        if sid == "captions.burn":
            st["cues"] = ctx.cues
            if not ctx.cues:
                rationale.append("Captions requested but no cues exist (no SRT imported and transcription "
                                 "unavailable) - captions were not added.")
                continue
        out_skills.append({"id": sid, "settings": st})

    rationale += ctx.notes
    # transitions must fit the shortest scene; shrink or drop rather than fail validation
    tr = next((e for e in out_skills if e["id"] == "transition.crossfade"), None)
    if tr is not None:
        spd = next((e["settings"].get("factor", 1.0) for e in out_skills if e["id"] == "time.speed"), 1.0)
        scenes, last = [], None
        for sg in ctx.segments:
            d = sg.dur / spd
            if scenes and sg.clip == last and not sg.brk:
                scenes[-1] += d
            else:
                scenes.append(d)
            last = sg.clip
        if len(scenes) > 1:
            want = float(tr["settings"].get("duration", 0.5))
            fit = round(min(want, min(scenes) / 2 - 0.05), 2)
            if fit < 0.15:
                out_skills.remove(tr)
                rationale.append("Transitions skipped: the shortest clip group is too brief to blend.")
            elif fit < want:
                tr["settings"]["duration"] = fit
                rationale.append(f"Transition shortened to {fit}s to fit the shortest clip group.")
    plan = {
        "version": 1, "goal": goal, "mode": mode,
        "sources": [{"path": str(Path(p).resolve())} for p in paths],
        "segments": [{"clip": s.clip, "start": round(s.start, 3), "end": round(s.end, 3),
                      **({"break": True} if s.brk else {})} for s in ctx.segments],
        "skills": out_skills,
        "export": {**validate.DEFAULT_EXPORT, **sel.export},
        "rationale": rationale,
    }
    return plan


# ------------------------------------------------------------ request parser
_NEG = r"(?:no|without|don'?t|do not|skip|never)\s+(?:\w+\s+){0,2}"
LOOKS = {"warm": "warm", "cool": "cool", "cold": "cool", "cinematic": "cinematic", "film look": "cinematic",
         "vivid": "vivid", "punchy colo": "vivid", "black and white": "bw", "black & white": "bw",
         "b&w": "bw", "monochrome": "bw", "faded": "faded", "vintage": "faded"}
TRANSITIONS = {"dip to black": "fadeblack", "fade to black": "fadeblack", "dip to white": "fadewhite",
               "wipe": "wipeleft", "slide": "slideleft", "dissolve": "dissolve", "crossfade": "fade",
               "cross fade": "fade", "cross-fade": "fade", "transition": "fade"}
UNAVAILABLE_KEYWORDS = {
    r"stabili[sz]|shaky|steady": "fx.stabilize", r"\bbeat\b|to the music|sync to music": "cut.beat_sync",
    r"\bj-?cut|\bl-?cut": "cut.jl_cuts", r"speed ramp": "cut.speed_ramp", r"match cut": "cut.match_cut",
    r"green screen|chroma|roto|mask|remove (the )?background|object": "ext.ai_masking",
    r"voice ?over|clone.*voice|text to speech|tts|generate.*(video|shot|scene)": "ext.generative_video",
    r"motion graphic|animated (title|text)|3d": "ext.motion_graphics",
    r"\bhdr\b|log footage|scopes": "ext.pro_color", r"multicam|proxy|\baaf\b": "ext.pro_workflow",
}


def _neg(text: str, pattern: str) -> bool:
    return re.search(_NEG + pattern, text) is not None


def parse_request(text: str, sel: Selection | None = None, total_duration: float | None = None) -> Selection:
    """Update `sel` from natural language. Unmet asks are recorded, never dropped silently."""
    sel = sel or Selection()
    t = text.lower()
    plat = platform_rule(t)
    if plat:
        sel.export["aspect"] = plat["aspect"]
        sel.notes.append(f"Platform '{plat['platform']}' -> {plat['aspect']}, {plat['lufs']:.0f} LUFS"
                         + (", captions" if plat["captions"] else "") + ".")
        sel.skills.setdefault("audio.loudnorm", {"target_lufs": plat["lufs"]})
        if plat["captions"] and not _neg(t, r"(caption|subtitle)"):
            sel.skills.setdefault("captions.burn", {})
    # aspect
    if re.search(r"9:16|vertical|portrait|1080x1920", t):
        sel.export["aspect"] = "9:16"
    elif re.search(r"\b1:1\b|square", t):
        sel.export["aspect"] = "1:1"
    elif re.search(r"4:5", t):
        sel.export["aspect"] = "4:5"
    elif re.search(r"16:9|landscape|widescreen|horizontal", t):
        sel.export["aspect"] = "16:9"
    if re.search(r"\b720p\b", t):
        sel.export["short_edge"] = 720
    if re.search(r"blur(red)? (background|bars)|blurred", t):
        sel.export["fit"] = "blur"
    elif re.search(r"letterbox|black bars|no crop|don'?t crop", t):
        sel.export["fit"] = "pad"
    # pauses
    if _neg(t, r"(pause|silence)"):
        sel.skills.pop("cut.remove_pauses", None)
    elif re.search(r"pause|silence|dead air|jump.?cut|tighten|ums?\b|filler|dead space", t):
        sel.skills["cut.remove_pauses"] = sel.skills.get("cut.remove_pauses", {})
    # captions
    if _neg(t, r"(caption|subtitle)"):
        sel.skills.pop("captions.burn", None)
    elif re.search(r"caption|subtitle|burn.?in text", t):
        sel.skills["captions.burn"] = sel.skills.get("captions.burn", {})
    # duration
    m = re.search(r"(\d+(?:\.\d+)?)\s*[- ]?(seconds?|secs?|minutes?|mins?|s)\b", t)
    if m and re.search(r"(make|cut|trim|keep|create|down to|under|around|about|\bto\b|-second|second)", t):
        val = float(m.group(1)) * (60 if m.group(2).startswith("min") else 1)
        if total_duration is None or val < total_duration:
            st = sel.skills.get("story.best_moments", {})
            st["target_duration"] = val
            sel.skills["story.best_moments"] = st
            st.setdefault("window", pacing_rule(plat))
    if re.search(r"\bhook\b|strongest moment first|start with the best", t):
        st = sel.skills.get("story.best_moments")
        if st is not None:
            st["hook_first"] = True
        else:
            sel.unsupported.append("A hook needs a target duration so the strongest moment can be selected "
                                   "(e.g. 'make it 30 seconds with a hook').")
    # speed
    m = re.search(r"(\d(?:\.\d+)?)\s*x\b", t)
    if m:
        sel.skills["time.speed"] = {"factor": float(m.group(1))}
    elif re.search(r"speed (it )?up|faster|time.?lapse", t):
        sel.skills["time.speed"] = {"factor": 1.25}
    elif re.search(r"slow(er| motion| down)?\b", t) and not re.search(r"slow(ly)? (paced|cinematic)", t):
        sel.skills["time.speed"] = {"factor": 0.75}
    # audio
    if re.search(r"normali[sz]|loudness|lufs|even out (the )?(volume|audio)|consistent volume", t):
        sel.skills.setdefault("audio.loudnorm", {"target_lufs": plat["lufs"] if plat else -14.0})
    m = re.search(r"(-\d+)\s*lufs", t)
    if m:
        sel.skills["audio.loudnorm"] = {"target_lufs": float(m.group(1))}
    if re.search(r"noise|clean(\s?up)? (the )?(audio|sound|voice)|denoise|hiss|rumble|muffled", t):
        sel.skills["audio.clean"] = {}
    if re.search(r"fade (in|out)|fades\b|fade the audio", t):
        sel.skills["audio.fades"] = {}
    if re.search(r"\bmusic\b|background track|soundtrack", t) and "audio.music_bed" not in sel.skills:
        sel.unsupported.append("Background music needs an audio file you provide (no music library is bundled).")
    # colour
    for kw, look in LOOKS.items():
        if kw in t:
            sel.skills["color.look"] = {"look": look}
            break
    if re.search(r"brighter|lighten|too dark", t):
        sel.skills["color.adjust"] = {**sel.skills.get("color.adjust", {}), "brightness": 0.08}
    if re.search(r"more contrast|punchier|contrasty", t):
        sel.skills["color.adjust"] = {**sel.skills.get("color.adjust", {}), "contrast": 1.15}
    if re.search(r"saturat|more colou?r", t):
        sel.skills["color.adjust"] = {**sel.skills.get("color.adjust", {}), "saturation": 1.25}
    # effects
    if re.search(r"sharpen|crisper", t):
        sel.skills["fx.sharpen"] = {}
    if re.search(r"vignette", t):
        sel.skills["fx.vignette"] = {}
    if re.search(r"grain|noisy (video|footage)|denoise (the )?video", t):
        sel.skills["fx.denoise"] = {}
    # transitions
    if not _neg(t, r"transition"):
        for kw, typ in TRANSITIONS.items():
            if kw in t:
                sel.skills["transition.crossfade"] = {"type": typ}
                break
    else:
        sel.skills.pop("transition.crossfade", None)
    # title
    m = re.search(r"(?:title|heading|text)[^\"“'‘]{0,25}[\"“'‘]([^\"”'’]+)[\"”'’]", text, re.I)
    if m:
        sel.skills["graphics.title"] = {"text": m.group(1).strip()}
    if re.search(r"logo|watermark", t) and "graphics.watermark" not in sel.skills:
        sel.unsupported.append("A logo/watermark needs a PNG file you provide.")
    # cinematic goal bundles
    if "cinematic" in t and "color.look" not in sel.skills:
        sel.skills["color.look"] = {"look": "cinematic"}
    # unavailable / external asks -> explain with the registry's own reason
    for pattern, cid in UNAVAILABLE_KEYWORDS.items():
        if re.search(pattern, t):
            cap = registry.get(cid)
            sel.unsupported.append(f"{cap.name}: {cap.status()[1]}")
    sel.unsupported = list(dict.fromkeys(sel.unsupported))
    return sel


def apply_transcription_default(sel: Selection) -> None:
    """If captions are wanted but no SRT was supplied, use transcription when it is available."""
    if "captions.burn" in sel.skills and not sel.caption_files:
        cap = registry.get("captions.transcribe")
        if cap.available:
            sel.skills.setdefault("captions.transcribe", {})
        else:
            sel.unsupported.append(f"Auto-transcription unavailable: {cap.status()[1]} "
                                   "Upload an SRT/VTT file to add captions.")


def auto_plan(paths: list[Path], goal: str, caption_files: dict[int, str] | None = None,
              overrides: dict | None = None) -> tuple[dict, Selection]:
    """Auto mode: choose skills from the goal using documented rules."""
    clips = _probe(paths)
    total = sum(c.duration for c in clips)
    sel = Selection(caption_files=dict(caption_files or {}))
    sel.export.update(overrides or {})
    has_audio = any(c.has_audio for c in clips)
    plat = platform_rule(goal)

    # baseline rules
    sel.notes.append(f"Source material: {len(clips)} clip(s), {total:.1f}s total"
                     + ("" if has_audio else ", no audio"))
    if has_audio:
        sel.skills["cut.remove_pauses"] = {}
        sel.notes.append("Rule: spoken footage -> tighten by removing pauses (jump-cut pacing).")
    parse_request(goal, sel, total)
    if has_audio and "audio.loudnorm" not in sel.skills:
        sel.skills["audio.loudnorm"] = {"target_lufs": -14.0 if (plat and plat["short"]) else -16.0}
        sel.notes.append("Rule: consistent loudness target on every export.")
    if len(clips) > 1 and "transition.crossfade" not in sel.skills and re.search(r"smooth|cinematic|transition", goal.lower()):
        sel.skills["transition.crossfade"] = {"type": "fade"}
    apply_transcription_default(sel)
    if "captions.burn" in sel.skills and not sel.caption_files and not registry.get("captions.transcribe").available:
        sel.skills.pop("captions.burn")  # nothing to burn; the reason is already in sel.unsupported
    plan = build_plan(paths, sel, goal, "auto")
    return plan, sel


# ------------------------------------------------------------ chat
@dataclass
class ChatTurn:
    user: str
    reply: str
    plan: dict


class ChatSession:
    """Incremental natural-language editing; every revision is kept."""

    def __init__(self, paths: list[Path], caption_files: dict[int, str] | None = None,
                 llm: Callable[[str], str] | None = None):
        self.paths = [Path(p) for p in paths]
        self.sel = Selection(caption_files=dict(caption_files or {}))
        self.total = sum(c.duration for c in _probe(self.paths))
        self.history: list[ChatTurn] = []
        self.llm = llm

    @property
    def plan(self) -> dict | None:
        return self.history[-1].plan if self.history else None

    def send(self, message: str) -> ChatTurn:
        before = copy.deepcopy(self.sel.skills), dict(self.sel.export)
        self.sel.unsupported, self.sel.notes = [], []
        if self.llm:
            llm_plan(message, self.sel, self.llm, self.total)
        parse_request(message, self.sel, self.total)
        apply_transcription_default(self.sel)
        if "captions.burn" in self.sel.skills and not self.sel.caption_files and \
                not registry.get("captions.transcribe").available:
            self.sel.skills.pop("captions.burn", None)
        plan = build_plan(self.paths, self.sel, message, "chat")
        changed = [k for k in self.sel.skills if k not in before[0] or self.sel.skills[k] != before[0].get(k)]
        changed += [f"export.{k}" for k, v in self.sel.export.items() if before[1].get(k) != v]
        lines = []
        lines.append("Updated: " + ", ".join(changed) if changed else "No change to the plan.")
        for u in self.sel.unsupported:
            lines.append("Could not do: " + u)
        turn = ChatTurn(message, "\n".join(lines), plan)
        self.history.append(turn)
        return turn

    def undo(self) -> None:
        if self.history:
            self.history.pop()


# ------------------------------------------------------------ optional LLM path
def llm_plan(message: str, sel: Selection, complete: Callable[[str], str], total: float) -> None:
    """Ask an LLM to choose registry skills. Output is JSON and is validated like any other plan:
    unknown/unavailable ids are rejected, so a bad answer cannot execute anything."""
    catalog = [{"id": c.id, "settings": {k: v["type"] for k, v in c.describe()["settings"].items()}}
               for c in registry.CAPS if c.available and c.kind == "feature" and c.stage != "analyze"
               or c.id in ("cut.remove_pauses", "story.best_moments")]
    prompt = (
        "You plan video edits. Choose only from these skills and return JSON "
        '{"skills": {"<id>": {<settings>}}, "export": {"aspect": "16:9|9:16|1:1|4:5"}}.\n'
        f"Source length: {total:.1f}s. Skills: {json.dumps(catalog)}\nRequest: {message}")
    try:
        data = json.loads(complete(prompt))
    except (ValueError, TypeError):
        sel.unsupported.append("LLM planner returned unreadable output; used the rule-based parser only.")
        return
    for sid, st in (data.get("skills") or {}).items():
        if sid in registry.REGISTRY and registry.get(sid).available and isinstance(st, dict):
            sel.skills[sid] = {**sel.skills.get(sid, {}), **st}
        else:
            sel.unsupported.append(f"LLM suggested unavailable skill '{sid}'.")
    sel.export.update({k: v for k, v in (data.get("export") or {}).items() if k in validate.DEFAULT_EXPORT})
