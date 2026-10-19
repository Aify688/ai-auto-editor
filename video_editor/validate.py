"""Plan validation and heuristic review.

A plan is plain JSON-able data:
{
  "version": 1, "goal": str, "mode": "auto|custom|chat",
  "sources":  [{"path": str}],
  "segments": [{"clip": int, "start": float, "end": float}],   # source timestamps
  "skills":   [{"id": str, "settings": {...}}],
  "export":   {"aspect","fit","short_edge","fps","crf","preset","audio_bitrate"},
  "rationale": [str]
}
`validate_plan` never runs FFmpeg for editing; it probes inputs only.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

from . import audiofx, effects, ffmpeg_ops, keyframes, registry
from .transitions import TRANSITION_TYPES

ASPECTS = {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1), "4:5": (4, 5)}
FITS = ("crop", "blur", "pad")
DEFAULT_EXPORT = {"aspect": "16:9", "fit": "crop", "short_edge": 1080, "fps": 30, "crf": 20,
                  "preset": "veryfast", "audio_bitrate": "160k"}
PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow")
REPEATABLE = {"graphics.title", "graphics.lower_third"}
MIN_SEGMENT = 0.2


class PlanError(ValueError):
    pass


@dataclass
class Validation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    clips: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_plan(plan: dict, clips: list | None = None) -> Validation:
    v = Validation()
    p = copy.deepcopy(plan)
    p.setdefault("version", 1)
    p.setdefault("rationale", [])
    exp = dict(DEFAULT_EXPORT)
    exp.update(p.get("export") or {})
    p["export"] = exp

    # ---- sources
    sources = p.get("sources") or []
    if not sources:
        v.errors.append("Plan has no sources.")
    if clips is None:
        clips = []
        for s in sources:
            path = Path(s.get("path", ""))
            if not path.exists():
                v.errors.append(f"Source not found: {path}")
                continue
            try:
                clips.append(ffmpeg_ops.probe_video(path))
            except ffmpeg_ops.Cancelled:
                raise
            except ffmpeg_ops.FFmpegError as e:
                v.errors.append(str(e).splitlines()[0])
    v.clips = clips
    if len(clips) != len(sources):
        v.errors.append("Not all sources could be read; cannot validate segments.")
        v.plan = p
        return v

    # ---- segments
    segs = p.get("segments") or []
    if not segs:
        v.errors.append("Plan has no segments.")
    fixed = []
    for i, s in enumerate(segs):
        try:
            ci, a, b = int(s["clip"]), float(s["start"]), float(s["end"])
        except (KeyError, TypeError, ValueError):
            v.errors.append(f"segments[{i}] needs clip/start/end numbers.")
            continue
        if not 0 <= ci < len(clips):
            v.errors.append(f"segments[{i}] refers to clip {ci}, but only {len(clips)} clip(s) exist.")
            continue
        dur = clips[ci].duration
        if a < 0:
            v.errors.append(f"segments[{i}] starts before 0 ({a}).")
        if a >= dur:
            v.errors.append(f"segments[{i}] starts at {a:.2f}s, beyond clip length {dur:.2f}s.")
            continue
        if b > dur + 0.05:
            v.warnings.append(f"segments[{i}] end {b:.2f}s clamped to clip length {dur:.2f}s.")
        b = min(b, dur)
        if b - a < (0.04 if s.get("freeze") else MIN_SEGMENT):
            v.errors.append(f"segments[{i}] is shorter than {MIN_SEGMENT}s ({b - a:.2f}s).")
            continue
        seg = {"clip": ci, "start": round(a, 3), "end": round(b, 3), **({"break": True} if s.get("break") else {})}
        if isinstance(s.get("bg"), dict) and s["bg"].get("matte"):
            seg["bg"] = s["bg"]            # AI background removal: matte video + replacement (see engine)
        try:
            rate = float(s.get("rate", 1.0))
            hold = float(s["freeze"]) if s.get("freeze") else None
        except (TypeError, ValueError):
            v.errors.append(f"segments[{i}].rate/freeze must be numbers.")
            continue
        if hold is not None:
            if not 0.1 <= hold <= 30:
                v.errors.append(f"segments[{i}].freeze must be 0.1-30 seconds.")
                continue
            seg["freeze"] = round(hold, 3)
            seg["rate"] = round((b - a) / hold, 4)
        elif abs(rate - 1.0) > 1e-6:
            if not 0.25 <= rate <= 4:
                v.errors.append(f"segments[{i}].rate must be between 0.25 and 4.")
                continue
            seg["rate"] = round(rate, 4)
        try:
            vol = float(s.get("volume", 1.0))
        except (TypeError, ValueError):
            vol = 1.0
        if abs(vol - 1.0) > 1e-6:
            seg["volume"] = round(min(2.0, max(0.0, vol)), 3)
        if audiofx.valid(s.get("audio_effect")):
            seg["audio_effect"] = s["audio_effect"]
        fx, flt = effects.normalize(s.get("effects"), s.get("filter"))
        if fx:
            seg["effects"] = fx
        if flt:
            seg["filter"] = flt
        if s.get("transition_type") in TRANSITION_TYPES:
            seg["transition_type"] = s["transition_type"]
        kfs = keyframes.normalize(s.get("keyframes"))
        if keyframes.is_animated(kfs):
            seg["keyframes"] = kfs
        focus = s.get("focus")
        if focus is not None:
            try:
                fx, fy = (float(f) for f in focus)
                if not (0 <= fx <= 1 and 0 <= fy <= 1):
                    raise ValueError
                seg["focus"] = [round(fx, 3), round(fy, 3)]
            except (TypeError, ValueError):
                v.errors.append(f"segments[{i}].focus must be two numbers in [0, 1].")
                continue
        fixed.append(seg)
    p["segments"] = fixed

    # ---- skills
    seen, norm = set(), []
    for i, entry in enumerate(p.get("skills") or []):
        sid = entry.get("id")
        if sid not in registry.REGISTRY:
            v.errors.append(f"skills[{i}]: unknown capability '{sid}'.")
            continue
        cap = registry.get(sid)
        if cap.kind not in ("feature",):
            v.errors.append(f"skills[{i}]: '{sid}' is a {cap.kind}, not an executable edit.")
            continue
        status, reason = cap.status()
        if status != registry.AVAILABLE:
            v.errors.append(f"'{sid}' is unavailable: {reason}")
            continue
        if sid in seen and sid not in REPEATABLE:
            v.errors.append(f"'{sid}' appears more than once.")
            continue
        seen.add(sid)
        settings, errs = cap.normalize_settings(entry.get("settings"))
        v.errors.extend(errs)
        for s in cap.settings:
            if s.type == "file" and settings.get(s.name) and not Path(settings[s.name]).exists():
                v.errors.append(f"{sid}: file not found: {settings[s.name]}")
        norm.append({"id": sid, "settings": settings})
    p["skills"] = norm
    ids = {e["id"] for e in norm}

    # ---- captions
    for e in norm:
        if e["id"] == "captions.burn":
            cues = e["settings"].get("cues") or []
            if not cues:
                v.errors.append("captions.burn has no cues (import an SRT/VTT or enable transcription).")
            good = []
            for j, c in enumerate(cues):
                try:
                    cc = {"clip": int(c.get("clip", 0)), "start": float(c["start"]), "end": float(c["end"]),
                          "text": str(c["text"]).strip()}
                except (KeyError, TypeError, ValueError):
                    v.errors.append(f"caption cue {j} is malformed.")
                    continue
                if not cc["text"] or cc["end"] <= cc["start"] or not 0 <= cc["clip"] < len(clips):
                    v.warnings.append(f"caption cue {j} skipped (empty text, bad times, or bad clip).")
                    continue
                good.append(cc)
            e["settings"]["cues"] = good

    # ---- export
    if exp["aspect"] != "match_first" and exp["aspect"] not in ASPECTS:
        v.errors.append(f"export.aspect '{exp['aspect']}' not in {list(ASPECTS) + ['match_first']}.")
    if exp["fit"] not in FITS:
        v.errors.append(f"export.fit '{exp['fit']}' not in {list(FITS)}.")
    if not 360 <= int(exp["short_edge"]) <= 2160:
        v.errors.append("export.short_edge must be 360-2160.")
    if not 10 <= int(exp["fps"]) <= 60:
        v.errors.append("export.fps must be 10-60.")
    if not 14 <= int(exp["crf"]) <= 35:
        v.errors.append("export.crf must be 14-35.")
    if exp["preset"] not in PRESETS:
        v.errors.append(f"export.preset must be one of {list(PRESETS)}.")
    if exp.get("video_bitrate_kbps") is not None and not 300 <= int(exp["video_bitrate_kbps"]) <= 100000:
        v.errors.append("export.video_bitrate_kbps must be 300-100000.")

    # ---- transitions
    if "transition.crossfade" in ids and fixed:
        t = next(e for e in norm if e["id"] == "transition.crossfade")["settings"]
        speed = next((e["settings"]["factor"] for e in norm if e["id"] == "time.speed"), 1.0)
        scenes = _scene_durations(fixed, speed)
        if len(scenes) < 2:
            v.warnings.append("transition.crossfade: only one clip group; no boundary to transition.")
        elif min(scenes) < 2 * t["duration"]:
            v.errors.append(f"transition duration {t['duration']}s needs every clip group to be at least "
                            f"{2 * t['duration']:.1f}s (shortest is {min(scenes):.1f}s).")

    # ---- music vs. no audio etc.
    if fixed and not any(clips[s["clip"]].has_audio for s in fixed) and ids & {"audio.clean", "audio.loudnorm"}:
        v.warnings.append("Selected clips have no audio; audio cleanup/normalisation has nothing to act on.")

    total = _program_duration(fixed, ids, norm)
    for e in norm:
        if e["id"] in ("graphics.title", "graphics.lower_third") and e["settings"]["start"] >= total:
            v.warnings.append(f"{e['id']} starts at {e['settings']['start']}s, after the {total:.1f}s program ends.")
    p["_estimated_duration"] = round(total, 2)
    v.plan = p
    return v


def _scene_durations(segs: list[dict], speed: float) -> list[float]:
    groups: list[float] = []
    last = None
    for s in segs:
        d = (s["end"] - s["start"]) / (speed * s.get("rate", 1.0))
        if last == s["clip"] and groups and not s.get("break"):
            groups[-1] += d
        else:
            groups.append(d)
        last = s["clip"]
    return groups


def _program_duration(segs, ids, norm) -> float:
    speed = next((e["settings"]["factor"] for e in norm if e["id"] == "time.speed"), 1.0)
    total = sum((s["end"] - s["start"]) / (speed * s.get("rate", 1.0)) for s in segs)
    if "transition.crossfade" in ids:
        t = next(e for e in norm if e["id"] == "transition.crossfade")["settings"]["duration"]
        total -= t * max(0, len(_scene_durations(segs, speed)) - 1)
    return total


def require_valid(plan: dict, clips=None) -> Validation:
    v = validate_plan(plan, clips)
    if not v.ok:
        raise PlanError("Plan failed validation:\n- " + "\n- ".join(v.errors))
    return v


def review_plan(plan: dict, clips: list) -> list[str]:
    """Heuristic editorial notes drawn from the reference doc. Not errors."""
    notes = []
    ids = {e["id"] for e in plan.get("skills", [])}
    exp = plan.get("export", {})
    segs = plan.get("segments", [])
    total = plan.get("_estimated_duration") or sum(s["end"] - s["start"] for s in segs)
    vertical = exp.get("aspect") == "9:16"
    if vertical and "captions.burn" not in ids:
        notes.append("Vertical short-form is usually watched muted: consider burned-in captions.")
    if "audio.loudnorm" not in ids and any(clips[s["clip"]].has_audio for s in segs):
        notes.append("No loudness target set; platforms normalise differently (-14 LUFS social is a safe default).")
    if vertical and total > 180:
        notes.append(f"{total:.0f}s is longer than the 3-minute Shorts/Reels limit.")
    if vertical or exp.get("aspect") == "1:1":
        long_shots = [s for s in segs if s["end"] - s["start"] > 7]
        if long_shots:
            notes.append(f"{len(long_shots)} shot(s) run longer than ~7 s; short-form usually changes visually "
                         "every 5-7 s (heuristic, not a measured rule).")
    if segs and total > 30 and "story.best_moments" not in ids and vertical:
        notes.append("First 3 seconds decide retention: check the opening shot is your strongest.")
    return notes
