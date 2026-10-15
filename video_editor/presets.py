"""AI style presets + switches -> Selection -> validated plan -> render.

The UI contains no editing logic: every switch maps to registry skills here,
so a control exists only if it changes the produced video.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import planning, registry
from .engine import RenderResult, execute_plan
from .ffmpeg_ops import ClipInfo

SWITCHES = ("autocut", "subtitles", "music", "transitions", "silence")


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    tagline: str
    icon: str                      # material icon name
    aspect: str
    switches: dict
    look: str | None = None
    lufs: float = -14.0
    hook: bool = False
    window: float = 4.0
    transition: tuple = ("fade", 0.5)
    clean_audio: bool = False
    fades: bool = False
    target: float = 30.0


PRESETS: dict[str, Preset] = {p.key: p for p in [
    Preset("dynamic", "Dynamic", "Fast cuts, high energy", "bolt", "16:9",
           {"autocut": True, "subtitles": False, "music": False, "transitions": True, "silence": True},
           look="vivid", lufs=-14.0, hook=True, window=2.0, transition=("fadewhite", 0.2), target=20.0),
    Preset("cinematic", "Cinematic", "Smooth fades, slow pacing, film grade", "movie", "16:9",
           {"autocut": False, "subtitles": False, "music": False, "transitions": True, "silence": False},
           look="cinematic", lufs=-16.0, transition=("fadeblack", 0.8), fades=True),
    Preset("vlog", "Vlog", "Natural cuts, clear speech, light fades", "videocam", "16:9",
           {"autocut": False, "subtitles": True, "music": False, "transitions": True, "silence": True},
           look="warm", lufs=-16.0, transition=("fade", 0.4), clean_audio=True),
    Preset("shorts", "Shorts", "Vertical 9:16, punchy and captioned", "smartphone", "9:16",
           {"autocut": True, "subtitles": True, "music": False, "transitions": False, "silence": True},
           lufs=-14.0, hook=True, window=3.0, clean_audio=True, target=30.0),
    Preset("promo", "Promotional", "Square 1:1, vivid and fast", "campaign", "1:1",
           {"autocut": True, "subtitles": True, "music": False, "transitions": True, "silence": True},
           look="vivid", lufs=-14.0, hook=True, window=3.0, transition=("wipeleft", 0.4), target=30.0),
]}

SWITCH_INFO = {
    "autocut": ("content_cut", "Auto cut", "Keeps the most active moments to reach a target length"),
    "subtitles": ("subtitles", "Subtitles", "Burns in captions (uploaded SRT/VTT, or transcribed speech)"),
    "music": ("music_note", "Background music", "Mixes your music file under the dialogue"),
    "transitions": ("auto_awesome_motion", "Smart transitions", "Blends between clips and selected moments"),
    "silence": ("volume_off", "Silence removal", "Cuts out pauses, keeping a natural breath"),
}


def blocking_problems(switches: dict, *, n_clips: int, has_srt: bool, music_path: str | None) -> list[str]:
    out = []
    if n_clips == 0:
        out.append("Upload a video first.")
    if switches.get("music") and not music_path:
        out.append("Background music is on: add a music file or switch it off.")
    return out


def subtitle_source_available(has_srt: bool) -> tuple[bool, str]:
    if has_srt:
        return True, "Using your uploaded captions."
    cap = registry.get("captions.transcribe")
    if cap.available:
        return True, "Speech will be transcribed automatically."
    return False, "Needs an SRT/VTT file or: " + cap.status()[1]


def build_selection(preset_key: str, switches: dict, *, total: float, target: float | None = None,
                    caption_files: dict | None = None, music_path: str | None = None,
                    whisper_model: str = "base", short_edge: int = 1080, overrides: dict | None = None
                    ) -> planning.Selection:
    p = PRESETS[preset_key]
    sel = planning.Selection(caption_files=dict(caption_files or {}))
    sel.export = {"aspect": p.aspect, "short_edge": short_edge, **(overrides or {})}
    sk = sel.skills
    sel.notes.append(f"Style: {p.name} ({sel.export['aspect']}, {p.lufs:.0f} LUFS)")
    if switches.get("autocut"):
        tgt = float(target or p.target)
        if total > tgt + 0.5:
            sk["story.best_moments"] = {"target_duration": tgt, "window": p.window, "hook_first": p.hook}
        else:
            sel.notes.append("Auto cut: footage is already within the target length.")
    if switches.get("silence"):
        sk["cut.remove_pauses"] = {}
    if switches.get("subtitles"):
        ok, why = subtitle_source_available(bool(sel.caption_files))
        if ok:
            sk["captions.burn"] = {}
            if not sel.caption_files:
                sk["captions.transcribe"] = {"model": whisper_model}
        else:
            sel.unsupported.append("Subtitles: " + why)
    if switches.get("music") and music_path:
        sk["audio.music_bed"] = {"path": music_path, "volume": 0.2, "duck": True}
    if switches.get("transitions"):
        sk["transition.crossfade"] = {"type": p.transition[0], "duration": p.transition[1]}
    if p.look:
        sk["color.look"] = {"look": p.look}
    if p.clean_audio:
        sk["audio.clean"] = {}
    if p.fades:
        sk["audio.fades"] = {}
    sk["audio.loudnorm"] = {"target_lufs": p.lufs}
    return sel


# ----------------------------------------------------------- generation with step events
def steps_for(switches: dict, target_active: bool = True) -> list[tuple[str, str, str]]:
    """(event key, label, material icon) for the steps this run will actually perform."""
    steps = [("analyze", "Analyzing footage", "troubleshoot")]
    if switches.get("autocut"):
        steps.append(("story.best_moments", "Picking best moments", "content_cut"))
    if switches.get("silence"):
        steps.append(("cut.remove_pauses", "Removing silence", "volume_off"))
    if switches.get("subtitles"):
        steps.append(("captions.transcribe", "Preparing subtitles", "subtitles"))
    steps.append(("render", "Cutting & resizing", "crop"))
    if switches.get("transitions"):
        steps.append(("join", "Adding transitions", "auto_awesome_motion"))
    steps.append(("master", "Audio, subtitles & style", "graphic_eq"))
    steps.append(("done", "Export ready", "check_circle"))
    return steps


def generate(paths: list[Path], preset_key: str, switches: dict, *, target: float | None,
             caption_files: dict | None, music_path: str | None, whisper_model: str, short_edge: int,
             overrides: dict | None = None,
             on_progress: Callable[[str, float], None] = lambda key, frac: None,
             out_dir: Path | None = None) -> tuple[RenderResult, planning.Selection]:
    """Run analysis + render. `on_progress(event_key, overall_fraction)`."""
    clips = planning._probe(paths)
    total = sum(c.duration for c in clips)
    sel = build_selection(preset_key, switches, total=total, target=target, caption_files=caption_files,
                          music_path=music_path, whisper_model=whisper_model, short_edge=short_edge,
                          overrides=overrides)
    n_analysis = max(1, len([k for k in planning.ANALYZE_ORDER if k in sel.skills]))
    seen = {"n": 0}

    def plan_event(key: str) -> None:
        seen["n"] += 1
        on_progress(key, 0.05 + 0.25 * seen["n"] / (n_analysis + 1))

    on_progress("analyze", 0.03)
    plan = planning.build_plan(paths, sel, preset_key, "auto", progress=plan_event)
    plan["preset"] = preset_key

    def render_event(frac: float, msg: str) -> None:
        key = "render" if frac < 0.62 else "join" if frac < 0.72 else "master" if frac < 0.99 else "done"
        on_progress(key, 0.3 + 0.7 * frac)

    res = execute_plan(plan, render_event, out_dir=out_dir)
    return res, sel
