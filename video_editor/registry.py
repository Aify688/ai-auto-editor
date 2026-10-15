"""Capability registry.

One entry per skill from "Video editing skills list.md" that we can act on.
A capability is `available` only if its handler resolves to a real callable
AND every dependency probe passes. Everything else is shown with the reason.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any

from . import deps

# status values
AVAILABLE = "available"
MISSING_DEP = "missing_dependency"
NOT_IMPLEMENTED = "not_implemented"
EXTERNAL = "external_tool"
BROKEN = "broken_handler"


@dataclass(frozen=True)
class Setting:
    name: str
    type: str                    # float | int | bool | choice | text | file
    default: Any = None
    min: float | None = None
    max: float | None = None
    choices: tuple = ()
    help: str = ""
    required: bool = False


@dataclass(frozen=True)
class Capability:
    id: str
    name: str
    category: str
    description: str
    kind: str = "feature"        # feature | planning_rule | project | external
    stage: str | None = None     # analyze | segment | join | master | overlay | export | plan
    inputs: tuple = ()
    settings: tuple = ()
    dependencies: tuple = ()
    handler_ref: str | None = None   # "module:function" inside video_editor
    external_tool: str | None = None
    doc_skills: tuple = ()           # skills in the reference doc this covers

    # -- status ------------------------------------------------------------
    def resolve_handler(self):
        if not self.handler_ref:
            return None
        mod, _, fn = self.handler_ref.partition(":")
        try:
            module = importlib.import_module(f"video_editor.{mod}")
            return getattr(module, fn)
        except (ImportError, AttributeError):
            return None

    def status(self) -> tuple[str, str]:
        """Return (status, human reason)."""
        if self.kind == "external" or self.external_tool and not self.handler_ref:
            tool = self.external_tool or "another tool"
            if self.dependencies:
                miss = deps.check(list(self.dependencies))
                if miss:
                    return MISSING_DEP, "Not implemented; would also need: " + "; ".join(miss)
            return (EXTERNAL if self.kind == "external" else NOT_IMPLEMENTED,
                    f"Needs {tool}; not performed by this app.")
        if not self.handler_ref:
            miss = deps.check(list(self.dependencies)) if self.dependencies else []
            extra = f" (would also need: {'; '.join(miss)})" if miss else ""
            return NOT_IMPLEMENTED, "No execution handler implemented yet" + extra
        if self.resolve_handler() is None:
            return BROKEN, f"Handler {self.handler_ref} not found"
        miss = deps.check(list(self.dependencies))
        if miss:
            return MISSING_DEP, "Missing: " + "; ".join(miss)
        return AVAILABLE, ""

    @property
    def available(self) -> bool:
        return self.status()[0] == AVAILABLE

    # -- settings ----------------------------------------------------------
    def normalize_settings(self, given: dict | None) -> tuple[dict, list[str]]:
        """Fill defaults, coerce types, enforce ranges. Returns (settings, errors)."""
        given = dict(given or {})
        out, errors = {}, []
        for s in self.settings:
            v = given.pop(s.name, s.default)
            if v is None:
                if s.required:
                    errors.append(f"{self.id}: setting '{s.name}' is required")
                out[s.name] = None
                continue
            try:
                if s.type == "float":
                    v = float(v)
                elif s.type == "int":
                    v = int(v)
                elif s.type == "bool":
                    v = bool(v)
                elif s.type in ("text", "file"):
                    v = str(v)
                if s.type in ("float", "int"):
                    if s.min is not None and v < s.min:
                        errors.append(f"{self.id}.{s.name}={v} below minimum {s.min}")
                    if s.max is not None and v > s.max:
                        errors.append(f"{self.id}.{s.name}={v} above maximum {s.max}")
                if s.type == "choice" and v not in s.choices:
                    errors.append(f"{self.id}.{s.name}='{v}' not in {list(s.choices)}")
            except (TypeError, ValueError):
                errors.append(f"{self.id}.{s.name}: cannot interpret {v!r} as {s.type}")
            out[s.name] = v
        for extra in given:
            if extra in ("cues",) and self.id == "captions.burn":
                out["cues"] = given[extra]
            else:
                errors.append(f"{self.id}: unknown setting '{extra}'")
        return out, errors

    def describe(self) -> dict:
        status, reason = self.status()
        return {
            "id": self.id, "name": self.name, "category": self.category, "kind": self.kind,
            "description": self.description, "stage": self.stage, "inputs": list(self.inputs),
            "settings": {s.name: {"type": s.type, "default": s.default, "min": s.min, "max": s.max,
                                  "choices": list(s.choices)} for s in self.settings},
            "dependencies": list(self.dependencies), "status": status, "reason": reason,
            "handler": self.handler_ref, "external_tool": self.external_tool,
            "covers": list(self.doc_skills),
        }


S = Setting
CAPS: list[Capability] = [
    # ---- cutting & trimming
    Capability("cut.trim", "Trim / assemble clips", "Cutting & Trimming",
               "Keep chosen source time ranges and join them in order (hard cuts).",
               stage="segment", inputs=("video",), settings=(), dependencies=("ffmpeg",),
               handler_ref="engine:render_segment",
               doc_skills=("Hard / straight cut", "Trimming (ripple, roll, slip, slide)", "Insert vs. overwrite edits",
                           "Assembly -> rough cut", "Montage and sequence building")),
    Capability("cut.remove_pauses", "Remove pauses (jump-cut tightening)", "Cutting & Trimming",
               "Detect silence and cut it out, keeping a small breathing pad around speech.",
               stage="analyze", inputs=("video with audio",),
               settings=(S("noise_db", "float", -30.0, -60, -10, help="Level below which audio counts as silence"),
                         S("min_pause", "float", 0.5, 0.1, 5.0, help="Shortest pause to remove (s)"),
                         S("padding", "float", 0.12, 0.0, 0.5, help="Silence kept on each side (s)"),
                         S("min_keep", "float", 0.3, 0.1, 5.0, help="Drop kept pieces shorter than this (s)")),
               dependencies=("ffmpeg",), handler_ref="skills:remove_pauses",
               doc_skills=("Jump cut", "Text-based / transcript editing (pause removal part)", "Pacing, timing, rhythm")),
    Capability("story.best_moments", "Select best moments", "Storytelling",
               "Pick the highest audio-energy / scene-activity windows to reach a target length; "
               "optionally move the strongest one to the start as a hook.",
               stage="analyze", inputs=("video",),
               settings=(S("target_duration", "float", 30.0, 3, 3600, required=True),
                         S("window", "float", 3.0, 1.0, 15.0, help="Moment length (s)"),
                         S("hook_first", "bool", False, help="Open with the strongest moment")),
               dependencies=("ffmpeg", "numpy"), handler_ref="skills:best_moments",
               doc_skills=("Hook construction", "Pacing, timing, rhythm", "Killing your darlings",
                           "Repurposing long-form", "Assembly -> rough cut -> fine cut")),
    Capability("time.speed", "Speed change", "Cutting & Trimming",
               "Constant speed-up or slow-down with pitch-preserving audio.",
               stage="segment", settings=(S("factor", "float", 1.25, 0.25, 4.0),),
               dependencies=("ffmpeg",), handler_ref="skills:speed",
               doc_skills=("Speed ramping and time remapping (constant speed only)",)),
    # ---- format
    Capability("format.resize", "Resize / reframe", "Format & Delivery",
               "Convert to a platform aspect ratio: centre-crop, blurred-background fit, or letterbox.",
               stage="export", inputs=("video",), settings=(), dependencies=("ffmpeg",),
               handler_ref="engine:resize_graph",
               doc_skills=("Aspect ratios", "Platform versioning", "Repurposing long-form (reframe)")),
    Capability("format.export", "Export encode", "Format & Delivery",
               "H.264/AAC MP4 with chosen fps, quality and resolution.",
               stage="export", settings=(), dependencies=("ffmpeg",), handler_ref="engine:encode_final",
               doc_skills=("Codecs and containers (H.264 delivery)", "Frame rates", "Bitrate (CRF)")),
    # ---- captions
    Capability("captions.import", "Import captions (SRT/VTT)", "Captions",
               "Use an existing subtitle file as caption cues for a clip.", stage="analyze",
               inputs=("srt/vtt file",), settings=(), dependencies=(), handler_ref="analysis:parse_srt",
               doc_skills=("Captions and subtitles (import)",)),
    Capability("captions.transcribe", "Auto-transcribe speech", "Captions",
               "Speech-to-text for caption cues using a local Whisper model.", stage="analyze",
               inputs=("video with speech",),
               settings=(S("model", "choice", "base", choices=("tiny", "base", "small", "medium")),),
               dependencies=("faster_whisper",), handler_ref="skills:transcribe",
               doc_skills=("Captions and subtitles (auto-transcribe)", "Text-based / transcript editing (transcript)")),
    Capability("captions.burn", "Burn-in captions", "Captions",
               "Render caption cues onto the video, kept inside the platform safe zone.",
               stage="overlay", inputs=("caption cues",),
               settings=(S("font_scale", "float", 0.045, 0.02, 0.1), S("box", "bool", True)),
               dependencies=("ffmpeg", "pillow"), handler_ref="skills:overlay_captions",
               doc_skills=("Safe-zone-aware captions", "Captions and subtitles (burn-in)", "Titles")),
    # ---- transitions
    Capability("transition.crossfade", "Transitions between clips", "Transitions",
               "Blend between different source clips (fade, dip to black/white, wipes, slides).",
               stage="join", inputs=("2+ clips",),
               settings=(S("type", "choice", "fade", choices=(
                   "fade", "fadeblack", "fadewhite", "dissolve", "wipeleft", "wiperight", "slideleft",
                   "slideright", "circleopen", "pixelize")),
                         S("duration", "float", 0.5, 0.1, 3.0)),
               dependencies=("ffmpeg", "filter:xfade"), handler_ref="engine:build_join",
               doc_skills=("Transitions (dissolve, dip, wipe)",)),
    # ---- audio
    Capability("audio.clean", "Dialogue cleanup", "Audio",
               "High-pass rumble filter and FFT noise reduction.", stage="master",
               settings=(S("highpass", "bool", True), S("denoise", "bool", True),
                         S("noise_reduction_db", "float", 12.0, 3, 40)),
               dependencies=("ffmpeg", "filter:afftdn"), handler_ref="skills:master_clean",
               doc_skills=("Dialogue cleanup and repair (denoise part)",)),
    Capability("audio.loudnorm", "Loudness normalize", "Audio",
               "EBU R128 loudness to a target (e.g. -14 LUFS social, -16 online, -23 broadcast).",
               stage="master", settings=(S("target_lufs", "float", -14.0, -30, -9),),
               dependencies=("ffmpeg",), handler_ref="skills:master_loudnorm",
               doc_skills=("Loudness compliance", "Level balancing")),
    Capability("audio.fades", "Audio fades", "Audio", "Fade program audio in/out.", stage="master",
               settings=(S("fade_in", "float", 0.3, 0, 10), S("fade_out", "float", 0.8, 0, 10)),
               dependencies=("ffmpeg",), handler_ref="skills:master_fades",
               doc_skills=("Level balancing and fades",)),
    Capability("audio.volume", "Voice gain", "Audio", "Raise or lower the original audio.", stage="master",
               settings=(S("gain_db", "float", 0.0, -30, 20),), dependencies=("ffmpeg",),
               handler_ref="skills:master_volume", doc_skills=("Level balancing",)),
    Capability("audio.music_bed", "Music bed with ducking", "Audio",
               "Mix your own music file under the dialogue; optionally duck it when someone speaks.",
               stage="master", inputs=("audio file",),
               settings=(S("path", "file", None, required=True), S("volume", "float", 0.25, 0.02, 1.0),
                         S("duck", "bool", True)),
               dependencies=("ffmpeg", "filter:sidechaincompress"), handler_ref="skills:master_music",
               doc_skills=("Music selection (mixing a supplied track)", "Level balancing")),
    # ---- color
    Capability("color.adjust", "Basic color correction", "Color",
               "Brightness, contrast, saturation, gamma.", stage="segment",
               settings=(S("brightness", "float", 0.0, -1, 1), S("contrast", "float", 1.0, 0, 3),
                         S("saturation", "float", 1.0, 0, 3), S("gamma", "float", 1.0, 0.1, 10)),
               dependencies=("ffmpeg",), handler_ref="skills:color_adjust",
               doc_skills=("Correction before grading",)),
    Capability("color.temperature", "White balance (temperature)", "Color",
               "Warm or cool the image by colour temperature.", stage="segment",
               settings=(S("kelvin", "int", 5500, 1000, 40000),), dependencies=("ffmpeg",),
               handler_ref="skills:color_temperature", doc_skills=("Correction before grading",)),
    Capability("color.look", "Look preset", "Color", "One-click grade: warm, cool, cinematic, vivid, bw, faded.",
               stage="segment", settings=(S("look", "choice", "cinematic", choices=tuple(
                   ["warm", "cool", "cinematic", "vivid", "bw", "faded"])),),
               dependencies=("ffmpeg",), handler_ref="skills:color_look",
               doc_skills=("Shot matching and LUTs (creative looks)",)),
    Capability("color.lut", "Apply LUT (.cube)", "Color", "Apply your own 3D LUT file.", stage="segment",
               inputs=(".cube file",), settings=(S("path", "file", None, required=True),),
               dependencies=("ffmpeg", "filter:lut3d"), handler_ref="skills:color_lut",
               doc_skills=("Shot matching and LUTs",)),
    # ---- effects
    Capability("fx.denoise", "Video denoise", "Effects", "Temporal/spatial noise reduction.", stage="segment",
               settings=(S("strength", "float", 3.0, 0.5, 10),), dependencies=("ffmpeg",),
               handler_ref="skills:fx_denoise"),
    Capability("fx.sharpen", "Sharpen", "Effects", "Unsharp-mask sharpening.", stage="segment",
               settings=(S("amount", "float", 0.8, 0.1, 2.0),), dependencies=("ffmpeg",),
               handler_ref="skills:fx_sharpen"),
    Capability("fx.vignette", "Vignette", "Effects", "Darken the frame edges.", stage="segment",
               settings=(S("angle", "float", 0.6, 0.1, 1.5),), dependencies=("ffmpeg",),
               handler_ref="skills:fx_vignette"),
    Capability("fx.punch_in", "Digital punch-in", "Effects", "Static centre zoom (cut-in style).", stage="segment",
               settings=(S("zoom", "float", 1.15, 1.02, 2.0),), dependencies=("ffmpeg",),
               handler_ref="skills:fx_punch_in", doc_skills=("Cut-in / insert",)),
    # ---- graphics
    Capability("graphics.title", "Title card text", "Graphics", "Text over the video for a time range.",
               stage="overlay", settings=(S("text", "text", None, required=True), S("start", "float", 0.0, 0, 3600),
                                          S("duration", "float", 3.0, 0.5, 60),
                                          S("position", "choice", "center", choices=("top", "center", "bottom"))),
               dependencies=("ffmpeg", "pillow"), handler_ref="skills:overlay_title",
               doc_skills=("Titles, lower thirds (static text only)",)),
    Capability("graphics.lower_third", "Lower third", "Graphics", "Name + subtitle bar, left aligned.",
               stage="overlay", settings=(S("name", "text", None, required=True), S("subtitle", "text", ""),
                                          S("start", "float", 0.5, 0, 3600), S("duration", "float", 4.0, 0.5, 60)),
               dependencies=("ffmpeg", "pillow"), handler_ref="skills:overlay_lower_third",
               doc_skills=("Titles, lower thirds (static text only)", "Brand consistency")),
    Capability("graphics.watermark", "Logo watermark", "Graphics", "Overlay a PNG logo for the whole video.",
               stage="overlay", inputs=("PNG file",),
               settings=(S("path", "file", None, required=True), S("position", "choice", "bottom_right",
                         choices=("top_left", "top_right", "bottom_left", "bottom_right")),
                         S("scale", "float", 0.15, 0.03, 0.5), S("opacity", "float", 0.85, 0.1, 1.0)),
               dependencies=("ffmpeg", "pillow"), handler_ref="skills:overlay_watermark",
               doc_skills=("Brand consistency",)),
    # ---- planning rules
    Capability("rule.platform_preset", "Platform preset rule", "Planning rules",
               "Goal mentions TikTok/Reels/Shorts/YouTube/etc. -> aspect, loudness target, captions, length cap.",
               kind="planning_rule", stage="plan", handler_ref="planning:platform_rule",
               doc_skills=("Platform versioning", "Aspect ratios", "Performance-ad creative")),
    Capability("rule.pacing", "Short-form pacing rule", "Planning rules",
               "Short-form goals use ~3 s moment windows and a visual change at least every 5-7 s.",
               kind="planning_rule", stage="plan", handler_ref="planning:pacing_rule",
               doc_skills=("Retention analytics (heuristic)", "Pacing, timing, rhythm")),
    Capability("rule.caption_safe_zone", "Caption safe-zone rule", "Planning rules",
               "Captions on vertical video sit above the bottom ~22% reserved by platform UI.",
               kind="planning_rule", stage="overlay", handler_ref="skills:overlay_captions",
               doc_skills=("Safe-zone-aware captions",)),
    Capability("rule.loudness_target", "Loudness target rule", "Planning rules",
               "Picks -14 LUFS for social, -16 for web/podcast, -23 for broadcast from the goal.",
               kind="planning_rule", stage="plan", handler_ref="planning:platform_rule",
               doc_skills=("Loudness compliance",)),
    # ---- project / review
    Capability("project.validate", "Plan validation", "Project & Review",
               "Check segments, settings, dependencies and files before anything renders.",
               kind="project", handler_ref="validate:validate_plan"),
    Capability("project.review", "Plan review checklist", "Project & Review",
               "Heuristic review: hook, pacing, captions, loudness, platform fit.",
               kind="project", handler_ref="validate:review_plan",
               doc_skills=("Narrative intuition (checklist only)", "Attention to detail", "Revision resilience")),
    Capability("project.save_plan", "Save/load plan JSON", "Project & Review",
               "Persist the structured plan next to the output so edits are repeatable.",
               kind="project", handler_ref="project:save_plan",
               doc_skills=("Media management (project files)", "Ownership")),
    Capability("project.export_edl", "Export EDL", "Project & Review",
               "CMX3600 EDL of the cut for hand-off to an NLE.", kind="project", handler_ref="project:export_edl",
               doc_skills=("Interchange and turnover (EDL)",)),
    Capability("project.chat_revisions", "Chat revision history", "Project & Review",
               "Apply notes as incremental changes to the current plan; each revision is kept.",
               kind="project", handler_ref="planning:ChatSession",
               doc_skills=("Diplomacy and handling notes", "Agentic / chat-driven editing",
                           "Communication", "Revision resilience")),
    # ---- not implemented / needs other tools
    Capability("fx.stabilize", "Video stabilization", "Effects", "Two-pass shake removal.", stage="segment",
               dependencies=("filter:vidstabdetect",), doc_skills=("Keying, masking, roto, tracking (stabilize)",)),
    Capability("cut.beat_sync", "Cut to the beat", "Cutting & Trimming", "Align cuts to music beats.",
               stage="analyze", dependencies=("librosa",), doc_skills=("Cutting to the beat",)),
    Capability("cut.jl_cuts", "J-cut / L-cut", "Cutting & Trimming", "Offset audio from picture at edit points.",
               stage="segment", doc_skills=("J-cut", "L-cut")),
    Capability("cut.speed_ramp", "Speed ramps", "Cutting & Trimming", "Animated speed changes.", stage="segment",
               doc_skills=("Speed ramping and time remapping",)),
    Capability("cut.match_cut", "Match cut / cutaway selection", "Storytelling",
               "Choose shots by visual/semantic similarity.", doc_skills=("Match cut", "Cut-in / insert and cutaway",
                                                                         "Visual composition / eye trace")),
    Capability("ai.semantic_search", "Semantic footage search", "AI",
               "Find moments by describing them.", dependencies=("anthropic_api",),
               doc_skills=("Media management and AI logging",)),
    Capability("ai.llm_planner", "LLM chat planner", "AI",
               "Natural-language request -> plan using an LLM (rule-based parser is used otherwise).",
               kind="planning_rule", stage="plan", dependencies=("anthropic_api",),
               handler_ref="planning:llm_plan",
               doc_skills=("Agentic / chat-driven editing",)),
    Capability("ext.ai_masking", "AI masking / roto / keying", "Advanced", "Object mask, chroma key, tracking.",
               kind="external", external_tool="Premiere / DaVinci Resolve (Magic Mask) or a roto tool",
               doc_skills=("Keying, masking, roto, tracking", "AI VFX and beauty")),
    Capability("ext.motion_graphics", "Animated motion graphics / 3D", "Advanced", "MOGRTs, kinetic type, 3D.",
               kind="external", external_tool="After Effects / Apple Motion / Remotion",
               doc_skills=("Titles, lower thirds, MOGRTs (animated)", "3D and type animation",
                           "Keyframing and easing", "Programmatic / templated video")),
    Capability("ext.generative_video", "Generative video / extend / voice", "Advanced",
               "Generate shots, extend clips, clone voice, TTS.", kind="external",
               external_tool="Firefly / Runway / Veo / ElevenLabs",
               doc_skills=("Generative video prompting", "Hybrid live-action + AI compositing",
                           "Voice cloning and TTS", "AI voice and TTS")),
    Capability("ext.pro_color", "HDR / scopes / multi-master grading", "Advanced",
               "Scopes, log/HDR conversion, multi-deliverable masters.", kind="external",
               external_tool="DaVinci Resolve / Baselight",
               doc_skills=("Reading scopes", "Log/RAW/HDR conversion", "Multi-deliverable HDR/SDR")),
    Capability("ext.audio_post", "Advanced audio repair / sound design", "Advanced",
               "Voice separation, spectral repair, sound design.", kind="external",
               external_tool="iZotope RX / Audition / Fairlight",
               doc_skills=("Dialogue cleanup and repair (separation)", "Sound design")),
    Capability("ext.pro_workflow", "Multicam, proxies, AAF/XML, shared storage", "Advanced",
               "Pro conform and collaboration workflows.", kind="external",
               external_tool="Premiere / Resolve / Avid / Frame.io",
               doc_skills=("Multicam", "Proxy / offline-online workflow", "Interchange and turnover (AAF/XML/OTIO)",
                           "Collaboration and shared storage", "Immersive delivery")),
    Capability("ext.content_credentials", "Content Credentials / AI disclosure", "Advanced",
               "Attach provenance metadata.", kind="external", external_tool="Adobe Content Authenticity / C2PA tools",
               doc_skills=("AI disclosure and data governance",)),
]

REGISTRY: dict[str, Capability] = {c.id: c for c in CAPS}
assert len(REGISTRY) == len(CAPS), "duplicate capability id"


def get(cap_id: str) -> Capability:
    return REGISTRY[cap_id]


def available_ids() -> list[str]:
    return [c.id for c in CAPS if c.available]
