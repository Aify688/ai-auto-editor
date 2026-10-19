"""Rule-based automatic editing: analysis results + style -> edit decision list (EDL).

Everything here is deterministic signal processing and explicit rules; no generative model.
Pipeline:  detect video type (action / talking_head / scenic / mixed)
        -> candidates (scenes ∩ non-silent audio, split into style-length windows)
        -> score (motion, audio activity, sharpness, faces, steadiness; adaptive weights)
        -> select (highlights with sensitivity-based threshold and per-scene caps)
        -> arrange (hook-first or chronological), merge contiguous windows
        -> fit to target length, or snap cuts to the music's beat grid
        -> smart-crop focus per clip (faces, else motion centroid)
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import layout as lay
from . import templates
from .media import STILL_SECONDS


# ------------------------------------------------------------------ video type detection

# Weight overrides per detected video type.  Each key maps to a weight
# adjustment dict that is *blended* with the style's base weights.
VIDEO_TYPE_WEIGHT_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "action": {
        "motion": 0.15, "audio": 0.05, "sharp": -0.05, "face": -0.05, "steady": -0.10, "activity": 0.0,
    },
    "talking_head": {
        "motion": -0.15, "audio": 0.15, "sharp": 0.0, "face": 0.15, "steady": 0.0, "activity": 0.10,
    },
    "scenic": {
        "motion": -0.10, "audio": -0.10, "sharp": 0.20, "face": -0.05, "steady": 0.15, "activity": -0.10,
    },
    "mixed": {},  # no adjustment
}

VIDEO_TYPE_LABELS: dict[str, str] = {
    "action": "Action / sports",
    "talking_head": "Talking head / interview",
    "scenic": "Scenic / landscape",
    "mixed": "Mixed content",
}


def detect_video_type(data: dict) -> str:
    """Classify footage as action, talking_head, scenic, or mixed based on aggregate signals.

    Uses the median of per-window features across all media to determine the
    dominant content type.  Thresholds are deliberately generous so only clearly
    dominant content gets a specific label; anything ambiguous is "mixed".
    """
    all_motion: list[float] = []
    all_face: list[float] = []
    all_activity: list[float] = []
    all_steady: list[float] = []

    for d in data.values():
        vis = d.get("visual", {})
        aud = d.get("audio", {})
        motion_vals = [v for v in vis.get("motion", []) if v is not None]
        if motion_vals:
            all_motion.extend(motion_vals)
        face_vals = vis.get("faces", [])
        if face_vals:
            face_ratio = sum(1 for f in face_vals if f) / max(1, len(face_vals))
            all_face.append(face_ratio)
        energy_vals = [v for v in aud.get("energy", []) if v is not None]
        if energy_vals:
            all_activity.extend(energy_vals)

    if not all_motion:
        return "mixed"

    med_motion = sorted(all_motion)[len(all_motion) // 2]
    max_motion = max(all_motion) if all_motion else 0
    avg_face = sum(all_face) / len(all_face) if all_face else 0

    # High face presence + low motion = talking head
    if avg_face > 0.5 and med_motion < max_motion * 0.35:
        return "talking_head"

    # High motion throughout = action
    if med_motion > max_motion * 0.45:
        return "action"

    # Low motion + low face = scenic
    if med_motion < max_motion * 0.2 and avg_face < 0.15:
        return "scenic"

    return "mixed"


def _adaptive_weights(spec_weights: dict, video_type: str) -> dict:
    """Blend style weights with video-type adjustments, clamping to [0, 1] and re-normalizing."""
    adj = VIDEO_TYPE_WEIGHT_ADJUSTMENTS.get(video_type, {})
    if not adj:
        return dict(spec_weights)
    blended = {}
    for k, v in spec_weights.items():
        blended[k] = max(0.0, v + adj.get(k, 0.0))
    total = sum(blended.values())
    if total > 0:
        blended = {k: round(v / total, 4) for k, v in blended.items()}
    return blended


# ------------------------------------------------------------------ boring section detection

# A window is "boring" only when nothing is happening on screen AND nothing is happening in the
# sound: near-zero frame difference together with (near-)silence.  Blurriness and "no faces" are NOT
# boring signals: they are relative measures that flag perfectly good scenery or B-roll.
BORING_THRESHOLDS = {
    "motion": 0.08,      # nearly static frame (relative to the 95th percentile of all footage)
    "audio": 0.06,       # barely audible
    "activity": 0.10,    # mostly silence
}

BORING_REASON_LABELS: dict[str, str] = {
    "static_silent": "Static picture and no sound",
    "blank": "Blank frame (no picture detail)",
    "dark": "Black or blown-out frames",
    "pause": "Pause between speech",
    "silence": "Long silence",
    "low_motion": "Very little movement",
    "silent": "No meaningful audio",
    "blurry": "Out of focus / blurry",
    "static": "Static shot, no activity",
    "low_energy": "Low overall energy",
}

LONG_SILENCE = 3.0          # silences at least this long are kept when something is visibly happening
RAW_BLANK_SHARPNESS = 5.0   # Laplacian variance below this = a featureless (blank/flat) frame
DARK_BRIGHTNESS = 0.03
BLOWN_BRIGHTNESS = 0.985
# Shortest run of "dead" frames that may be cut, in seconds, per editing intensity.
DEAD_MIN_RUN = {"light": 3.0, "balanced": 1.5, "aggressive": 1.0}


def _boring_reason(feats: dict) -> str | None:
    """Window-level check: static picture AND (quiet sound) -> boring; anything else is kept."""
    if feats.get("motion", 1.0) >= BORING_THRESHOLDS["motion"]:
        return None
    quiet = feats.get("audio", 1.0) < BORING_THRESHOLDS["audio"] or feats.get("activity", 1.0) < BORING_THRESHOLDS["activity"]
    return "static_silent" if quiet else None


def mark_boring(windows: list["Window"]) -> tuple[list["Window"], list["Window"]]:
    """Partition windows into (good, boring).  Each boring window gets a reason."""
    good, boring = [], []
    for w in windows:
        reason = _boring_reason(w.feats)
        if reason:
            w.boring = True
            w.boring_reason = reason
            boring.append(w)
        else:
            good.append(w)
    return good, boring


def _dead_runs(d: dict, norms: dict, dur: float, has_audio: bool, min_run: float) -> list[tuple[float, float, str]]:
    """Runs of at least *min_run* seconds in which nothing worth keeping happens, from the per-0.5 s
    feature tracks: blank/flat frames, black or blown-out frames, or a static picture with silent audio.
    Static footage WITH sound (a talking head, ambience, music) is never flagged."""
    vis, aud = d["visual"], d["audio"]
    vstep = vis.get("step", 0.5)
    astep = aud.get("step", 0.5)
    motion, sharp, bright = vis.get("motion", []), vis.get("sharpness", []), vis.get("brightness", [])
    energy = aud.get("energy", [])
    silences = aud.get("silences", [])
    n = int(math.ceil(dur / vstep))
    motion_floor = max(0.08 * norms.get("motion", 0.0), 0.004)
    audio_floor = 0.06 * norms.get("audio", 0.0)

    def in_silence(a: float, b: float) -> bool:
        covered = sum(max(0.0, min(b, y) - max(a, x)) for x, y in silences)
        return covered >= 0.7 * (b - a)

    steps: list[str | None] = []
    for i in range(n):
        t0, t1 = i * vstep, min(dur, (i + 1) * vstep)
        m = motion[i] if i < len(motion) else None
        sh = sharp[i] if i < len(sharp) else None
        br = bright[i] if i < len(bright) else None
        reason = None
        # A featureless / black / blown-out frame is dead whatever the frame difference says (the first
        # frame after a hard cut always shows a motion spike).
        if sh is not None and sh < RAW_BLANK_SHARPNESS:
            reason = "blank"
        elif br is not None and (br < DARK_BRIGHTNESS or br > BLOWN_BRIGHTNESS):
            reason = "dark"
        elif has_audio and m is not None and m <= motion_floor:
            j = int(t0 / astep)
            quiet = in_silence(t0, t1) or (energy and j < len(energy) and energy[j] is not None and energy[j] < audio_floor)
            if quiet:
                reason = "static_silent"
        steps.append(reason)

    runs: list[tuple[float, float, str]] = []
    i = 0
    while i < n:
        if steps[i] is None:
            i += 1
            continue
        j = i
        while j < n and steps[j] is not None:
            j += 1
        a, b = i * vstep, min(dur, j * vstep)
        if b - a >= min_run:
            kinds = [k for k in steps[i:j]]
            runs.append((a, b, max(set(kinds), key=kinds.count)))
        i = j
    return runs


def _visibly_active(vis: dict, a: float, b: float, norms: dict) -> bool:
    """True when at least a third of the 0.5 s steps in [a, b] show real movement (a single cut or
    flash at a scene boundary does not count)."""
    step = vis.get("step", 0.5)
    motion = vis.get("motion", [])
    floor = max(0.08 * norms.get("motion", 0.0), 0.004)
    chunk = [v for v in motion[int(a / step): max(int(a / step) + 1, int(math.ceil(b / step)))] if v is not None]
    return bool(chunk) and sum(1 for v in chunk if v > floor) >= max(1, len(chunk) // 3)


def _merge_cuts(cuts: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    out: list[list] = []
    for a, b, r in sorted(cuts):
        if out and a <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b, r])
    return [(a, b, r) for a, b, r in out]


@dataclass(frozen=True)
class StyleSpec:
    key: str
    name: str
    win_min: float
    win_max: float
    target_ratio: float          # auto target = usable footage x ratio, clamped to [target_min, target_max]
    target_min: float
    target_max: float
    order: str                   # "hook" | "chronological"
    transition: tuple            # (xfade type, seconds)
    look: str
    lufs: float
    weights: dict
    per_scene: int | None        # max windows per scene in the first selection pass
    jump_cuts: bool              # hard cuts (no transition) between pieces of one scene
    clean_audio: bool
    fades: bool
    image_len: float
    min_piece: float             # shortest kept piece after scene/silence splitting


STYLES: dict[str, StyleSpec] = {s.key: s for s in [
    StyleSpec("dynamic", "Dynamic", 1.2, 2.4, 0.4, 8, 30, "hook", ("fadewhite", 0.2), "vivid", -14.0,
              {"motion": 0.45, "audio": 0.25, "activity": 0.0, "sharp": 0.2, "face": 0.1, "steady": 0.0},
              per_scene=2, jump_cuts=False, clean_audio=False, fades=False, image_len=1.6,
              min_piece=0.8),
    StyleSpec("cinematic", "Cinematic", 3.5, 6.0, 0.6, 15, 60, "chronological", ("fade", 1.0), "cinematic", -16.0,
              {"motion": 0.1, "audio": 0.05, "activity": 0.0, "sharp": 0.45, "face": 0.1, "steady": 0.3},
              per_scene=1, jump_cuts=False, clean_audio=False, fades=True, image_len=4.0,
              min_piece=1.5),
    StyleSpec("vlog", "Vlog", 2.0, 10.0, 1.0, 10, 300, "chronological", ("fade", 0.35), "warm", -16.0,
              {"motion": 0.05, "audio": 0.15, "activity": 0.5, "sharp": 0.15, "face": 0.15, "steady": 0.0},
              per_scene=None, jump_cuts=True, clean_audio=True, fades=False, image_len=3.0,
              min_piece=0.4),
    StyleSpec("travel", "Travel", 2.0, 4.5, 0.5, 10, 45, "chronological", ("dissolve", 0.6), "vivid", -15.0,
              {"motion": 0.2, "audio": 0.1, "activity": 0.05, "sharp": 0.35, "face": 0.1, "steady": 0.2},
              per_scene=2, jump_cuts=False, clean_audio=False, fades=True, image_len=3.2,
              min_piece=1.0),
    StyleSpec("marketing", "Marketing", 1.0, 2.0, 0.35, 6, 25, "hook", ("fadewhite", 0.15), "vivid", -13.0,
              {"motion": 0.4, "audio": 0.3, "activity": 0.0, "sharp": 0.2, "face": 0.1, "steady": 0.0},
              per_scene=2, jump_cuts=True, clean_audio=False, fades=False, image_len=1.3,
              min_piece=0.6),
    StyleSpec("social", "Social Media", 0.9, 1.8, 0.3, 6, 20, "hook", ("fadewhite", 0.12), "vivid", -13.0,
              {"motion": 0.4, "audio": 0.25, "activity": 0.1, "sharp": 0.15, "face": 0.1, "steady": 0.0},
              per_scene=2, jump_cuts=True, clean_audio=False, fades=False, image_len=1.1,
              min_piece=0.5),
    StyleSpec("energetic", "Energetic", 1.0, 2.2, 0.4, 8, 30, "hook", ("fadewhite", 0.18), "vivid", -14.0,
              {"motion": 0.45, "audio": 0.25, "activity": 0.0, "sharp": 0.2, "face": 0.1, "steady": 0.0},
              per_scene=2, jump_cuts=False, clean_audio=False, fades=False, image_len=1.4, min_piece=0.7),
    StyleSpec("minimal", "Minimal", 3.0, 5.5, 0.55, 12, 60, "chronological", ("fade", 0.5), "none", -16.0,
              {"motion": 0.1, "audio": 0.1, "activity": 0.1, "sharp": 0.4, "face": 0.1, "steady": 0.2},
              per_scene=1, jump_cuts=False, clean_audio=False, fades=True, image_len=3.5, min_piece=1.4),
    StyleSpec("documentary", "Documentary", 2.5, 9.0, 0.7, 15, 180, "chronological", ("fade", 0.6), "faded", -16.0,
              {"motion": 0.05, "audio": 0.2, "activity": 0.3, "sharp": 0.2, "face": 0.2, "steady": 0.05},
              per_scene=None, jump_cuts=True, clean_audio=True, fades=True, image_len=4.0, min_piece=1.0),
    StyleSpec("professional", "Professional", 2.5, 6.0, 0.6, 12, 60, "chronological", ("fade", 0.6), "none", -16.0,
              {"motion": 0.1, "audio": 0.1, "activity": 0.1, "sharp": 0.3, "face": 0.25, "steady": 0.15},
              per_scene=1, jump_cuts=False, clean_audio=True, fades=True, image_len=3.5,
              min_piece=1.2),
]}

# "auto" isn't a fixed StyleSpec: build_edl() detects the content type first (see
# detect_video_type) and resolves it to one of the concrete styles above.
AUTO_STYLE_MAP = {
    "action": "dynamic",
    "talking_head": "vlog",
    "scenic": "cinematic",
    "mixed": "travel",
}

# Editing intensity -> (highlight sensitivity, boring-removal on/off, selection cap multiplier).
# Light keeps more footage (higher sensitivity, no boring-removal); aggressive is the opposite.
INTENSITY_PRESETS: dict[str, dict] = {
    "light": {"sensitivity_bonus": 0.25, "boring_removal": False},
    "balanced": {"sensitivity_bonus": 0.0, "boring_removal": True},
    "aggressive": {"sensitivity_bonus": -0.25, "boring_removal": True},
}

PAUSE_PAD = 0.12

# Caption look bundles (mirror frontend/src/lib/styles.ts CAPTION_PRESETS) and each style's default.
CAPTION_PRESETS: dict[str, dict] = {
    "classic": {"fontSize": "medium", "position": "bottom", "color": "#FFFFFF", "background": "box", "highlightColor": "#FFD700",
                "uppercase": False, "preset": "classic", "karaoke": False, "animation": "none"},
    "bold": {"fontSize": "large", "position": "bottom", "color": "#FFFFFF", "background": "outline", "highlightColor": "#FFD700",
             "uppercase": True, "preset": "bold", "karaoke": False, "animation": "pop"},
    "karaoke": {"fontSize": "large", "position": "bottom", "color": "#FFFFFF", "background": "outline", "highlightColor": "#FFD700",
                "uppercase": False, "preset": "karaoke", "karaoke": True, "animation": "none"},
    "dynamic": {"fontSize": "large", "position": "center", "color": "#FFFFFF", "background": "outline", "highlightColor": "#00E5FF",
                "uppercase": True, "preset": "dynamic", "karaoke": True, "animation": "pop"},
    "cinematic": {"fontSize": "small", "position": "bottom", "color": "#F5F5F5", "background": "outline", "highlightColor": "#FFD700",
                  "uppercase": False, "preset": "cinematic", "karaoke": False, "animation": "fade"},
}
STYLE_CAPTION_PRESET = {"energetic": "dynamic", "dynamic": "dynamic", "social": "dynamic", "marketing": "bold",
                        "cinematic": "cinematic", "travel": "cinematic", "minimal": "classic", "documentary": "classic",
                        "vlog": "classic", "professional": "classic"}


@dataclass
class Window:
    media_id: str
    media_index: int
    scene: int
    start: float
    end: float
    bounds: tuple                # (start, end) of the enclosing scene, for beat-sync extension
    score: float = 0.0
    feats: dict = field(default_factory=dict)
    boring: bool = False         # Phase 2: flagged as boring/low-quality
    boring_reason: str | None = None

    @property
    def dur(self) -> float:
        return self.end - self.start


def _p95(values: list[float]) -> float:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return 0.0
    return vals[min(len(vals) - 1, int(0.95 * (len(vals) - 1)))] or (vals[-1] or 0.0)


def _mean(values: list, a: float, b: float, step: float) -> float | None:
    i0 = int(a / step)
    i1 = max(i0 + 1, int(math.ceil(b / step)))
    chunk = [v for v in values[i0:i1] if v is not None]
    return sum(chunk) / len(chunk) if chunk else None


def _subtract(a: float, b: float, cuts: list) -> list[tuple[float, float]]:
    pieces, pos = [], a
    for s, e in sorted(cuts):
        if e <= pos or s >= b:
            continue
        if s > pos:
            pieces.append((pos, min(s, b)))
        pos = max(pos, e)
    if pos < b:
        pieces.append((pos, b))
    return pieces


def _short_name(name: str) -> str:
    stem = Path(name).stem
    return stem if len(stem) <= 18 else stem[:17] + "…"


# ------------------------------------------------------------------ candidates + scoring
def candidates(spec: StyleSpec, settings, visuals: list[dict], data: dict, notes: list[str],
               weights: dict | None = None, intensity: str = "balanced", sensitivity: float = 0.5,
               removed: list[dict] | None = None, excluded: list[dict] | None = None) -> list[Window]:
    removed = removed if removed is not None else []
    excluded = excluded if excluded is not None else []
    norms = {
        "motion": _p95([v for d in data.values() for v in d["visual"].get("motion", [])]),
        "sharp": _p95([v for d in data.values() for v in d["visual"].get("sharpness", [])]),
        "audio": _p95([v for d in data.values() for v in d["audio"].get("energy", [])]),
    }
    out: list[Window] = []
    min_piece = spec.min_piece
    min_run = DEAD_MIN_RUN.get(intensity, 1.5) * (0.5 + sensitivity)
    kept_silent = 0

    def split_piece(mi: int, mid: str, si: int, pa: float, pb: float, bounds: tuple) -> None:
        length = pb - pa
        if length < min_piece:
            return
        n = max(1, math.ceil(length / spec.win_max))
        if length / n < spec.win_min and n > 1:
            n = max(1, int(length // spec.win_min))
        seg = length / n
        for k in range(n):
            out.append(Window(mid, mi, si, round(pa + k * seg, 3), round(pa + (k + 1) * seg, 3), bounds))

    for mi, m in enumerate(visuals):
        d = data[m["id"]]
        dur = float(m["duration"])
        if m["kind"] == "image":
            ln = min(spec.image_len, STILL_SECONDS)
            w = Window(m["id"], mi, 0, 0.0, ln, (0.0, STILL_SECONDS))
            sharp = _mean(d["visual"].get("sharpness", []), 0, 1, 0.5) or 0.0
            w.feats = {"sharp": min(1.0, sharp / norms["sharp"]) if norms["sharp"] else 0.5}
            w.score = 0.35 + 0.3 * w.feats["sharp"]
            out.append(w)
            continue
        scenes = d["scenes"] if settings.sceneDetection else [[0.0, dur]]
        silences = d["audio"].get("silences", [])
        vstep = d["visual"].get("step", 0.5)
        active_ratio = 1 - sum(min(b, dur) - a for a, b in silences) / dur if dur else 1
        use_silence = settings.removeSilence and m["has_audio"] and silences and 0.15 <= active_ratio <= 0.97
        cuts: list[tuple[float, float, str]] = []
        if use_silence:
            for a, b in silences:
                if b - a <= 2 * PAUSE_PAD:
                    continue
                long_run = (b - a) >= LONG_SILENCE
                if long_run and intensity != "aggressive":
                    if _visibly_active(d["visual"], a, b, norms):
                        kept_silent += 1          # silent but something is visibly happening: keep
                        continue
                cuts.append((a + PAUSE_PAD, b - PAUSE_PAD, "silence" if long_run else "pause"))
        if getattr(settings, "boringRemoval", True):
            for a, b, reason in _dead_runs(d, norms, dur, bool(m["has_audio"]), min_run):
                cuts.append((a + PAUSE_PAD, b - PAUSE_PAD, reason))
        cuts = _merge_cuts([c for c in cuts if c[1] - c[0] > 0.05])
        for a, b, reason in cuts:
            removed.append({"mediaId": m["id"], "start": round(a, 3), "end": round(min(b, dur), 3),
                            "reason": reason, "label": BORING_REASON_LABELS.get(reason, reason)})
        before = len(out)
        cut_ab = [(a, b) for a, b, _ in cuts]
        for si, (sa, sb) in enumerate(scenes):
            sb = min(sb, dur)
            pieces = _subtract(sa, sb, cut_ab) if cut_ab else [(sa, sb)]
            for pa, pb in pieces:
                split_piece(mi, m["id"], si, pa, pb, (sa, sb))
        if len(out) == before:
            cut_total = sum(b - a for a, b, _ in cuts)
            if cuts and cut_total >= 0.9 * dur:
                reasons = sorted({BORING_REASON_LABELS.get(r, r) for _, _, r in cuts})
                excluded.append({"mediaId": m["id"], "name": m["name"],
                                 "reason": "No usable segments: " + ", ".join(reasons).lower() + " throughout."})
                removed[:] = [r for r in removed if r["mediaId"] != m["id"]]
            else:
                # The cuts left only fragments shorter than the style's minimum piece: keep the
                # footage rather than dropping the whole video.
                removed[:] = [r for r in removed if r["mediaId"] != m["id"]]
                for si, (sa, sb) in enumerate(scenes):
                    split_piece(mi, m["id"], si, sa, min(sb, dur), (sa, min(sb, dur)))
                if len(out) == before:
                    split_piece(mi, m["id"], 0, 0.0, dur, (0.0, dur))
    if removed:
        by: dict[str, float] = {}
        for r in removed:
            by[r["reason"]] = by.get(r["reason"], 0.0) + r["end"] - r["start"]
        parts = ", ".join(f"{v:.1f}s {BORING_REASON_LABELS.get(k, k).lower()}" for k, v in sorted(by.items(), key=lambda kv: -kv[1]))
        notes.append(f"Removed {sum(by.values()):.1f}s in {len(removed)} cut(s): {parts}.")
    if kept_silent:
        notes.append(f"Kept {kept_silent} silent section(s) of {LONG_SILENCE:.0f}s or more because something is "
                     "visibly happening in them.")
    effective_weights = weights or spec.weights
    for w in out:
        if w.feats:
            continue
        _score(effective_weights, w, data[w.media_id], norms)
    return out


def _score(weights: dict, w: Window, d: dict, norms: dict) -> None:
    """Score a window using the given weights (may be adaptive or style-default)."""
    vis, aud = d["visual"], d["audio"]
    step_v, step_a = vis.get("step", 0.5), aud.get("step", 0.5)
    motion = _mean(vis.get("motion", []), w.start, w.end, step_v) or 0.0
    sharp = _mean(vis.get("sharpness", []), w.start, w.end, step_v) or 0.0
    bright = _mean(vis.get("brightness", []), w.start, w.end, step_v)
    energy = _mean(aud.get("energy", []), w.start, w.end, step_a) or 0.0
    faces = vis.get("faces", [])[int(w.start / step_v): max(int(w.start / step_v) + 1, int(math.ceil(w.end / step_v)))]
    face = sum(1 for f in faces if f) / max(1, len(faces))
    silent = sum(max(0.0, min(b, w.end) - max(a, w.start)) for a, b in aud.get("silences", []))
    activity = 1 - silent / w.dur if aud.get("energy") else 0.0
    f = {
        "motion": min(1.0, motion / norms["motion"]) if norms["motion"] else 0.0,
        "sharp": min(1.0, sharp / norms["sharp"]) if norms["sharp"] else 0.0,
        "audio": min(1.0, energy / norms["audio"]) if norms["audio"] else 0.0,
        "activity": max(0.0, activity),
        "face": face,
    }
    f["steady"] = 1 - f["motion"]
    score = sum(weights[k] * f[k] for k in weights)
    if bright is not None and (bright < 0.06 or bright > 0.96):
        score *= 0.5                    # near-black or blown-out frames
    w.feats = {k: round(v, 3) for k, v in f.items()}
    w.score = round(score, 4)


# ------------------------------------------------------------------ selection
def auto_target(spec: StyleSpec, usable: float) -> float:
    return min(usable, max(spec.target_min, min(spec.target_max, usable * spec.target_ratio)))


def _estimate(chosen: list[Window], d: float) -> float:
    return sum(w.dur for w in chosen) - d * max(0, len(chosen) - 1)


def _media_budgets(cands: list[Window], target: float, spec: StyleSpec) -> tuple[list[str], dict]:
    """Seconds each source video should contribute: its proportional share of the target, but never
    less than half an equal share (and never more than it has), so a lower-scoring video is not
    squeezed out by a higher-scoring one."""
    usable: dict[str, float] = {}
    for w in cands:
        usable[w.media_id] = usable.get(w.media_id, 0.0) + w.dur
    order = list(usable)
    total = sum(usable.values()) or 1.0
    floor_each = target / (2 * max(1, len(order)))
    budget = {mid: min(usable[mid], max(target * usable[mid] / total, floor_each, spec.win_min)) for mid in order}
    return order, budget


def _seed_per_media(cands: list[Window], target: float, spec: StyleSpec, by_score: bool) -> list[Window]:
    order, budget = _media_budgets(cands, target, spec)
    if len(order) < 2:
        return []
    seeds: list[Window] = []
    for mid in order:
        mine = [w for w in cands if w.media_id == mid]
        got = 0.0
        if by_score:
            ranked = sorted(mine, key=lambda w: (-w.score, w.start))
            for w in ranked:
                if got >= budget[mid] and seeds and any(x.media_id == mid for x in seeds):
                    break
                seeds.append(w)
                got += w.dur
        else:
            chrono = sorted(mine, key=lambda w: w.start)
            n = 1
            while n < len(chrono) and sum(w.dur for w in chrono[:1]) * n < budget[mid]:
                n += 1
            idx = sorted({round(i * (len(chrono) - 1) / max(1, n - 1)) for i in range(n)}) if n > 1 else [0]
            seeds.extend(chrono[i] for i in idx)
    return seeds


def select(spec: StyleSpec, cands: list[Window], target: float, highlight: bool, d: float,
           notes: list[str], sensitivity: float = 0.5, weights: dict | None = None) -> list[Window]:
    """Select candidate windows to include in the edit.

    *sensitivity* (0–1) controls how strict the score threshold is:
      0.0 = only the very best moments (aggressive filtering)
      0.5 = balanced (default, same behavior as before)
      1.0 = keep almost everything above the minimum quality bar
    """
    if not cands:
        return []
    if _estimate(cands, d) <= target + 0.05:
        return list(cands)
    if highlight:
        # Apply a score threshold based on sensitivity.
        # At sensitivity=0.0 the threshold is at the 75th percentile of scores.
        # At sensitivity=0.5 it's at the 25th percentile (original behavior).
        # At sensitivity=1.0 the threshold is effectively 0 (keep everything that fits).
        scores_sorted = sorted(w.score for w in cands)
        if sensitivity < 1.0:
            # Map sensitivity 0→0.75, 0.5→0.25, 1.0→0.0 percentile
            pct = max(0.0, 0.75 - sensitivity * 0.75)
            threshold = scores_sorted[min(len(scores_sorted) - 1, int(pct * (len(scores_sorted) - 1)))]
        else:
            threshold = 0.0

        ranked = sorted(cands, key=lambda w: (-w.score, w.media_index, w.start))
        # Each video first gets its own share (best windows of THAT video), then the rest of the
        # target is filled by global ranking.  Without this, one high-scoring video takes it all.
        chosen: list[Window] = _seed_per_media(cands, target, spec, by_score=True)
        per: dict = {}
        for w in chosen:
            per[(w.media_id, w.scene)] = per.get((w.media_id, w.scene), 0) + 1
        # Adjust per-scene cap based on sensitivity (more = more clips per scene)
        base_cap = spec.per_scene
        if base_cap is not None:
            adj_cap = max(1, int(base_cap * (1 + sensitivity)))
        else:
            adj_cap = None
        for cap in ([adj_cap] if adj_cap else []) + [None]:
            for w in ranked:
                if _estimate(chosen, d) >= target:
                    break
                if w.score < threshold and _estimate(chosen, d) > target * 0.5:
                    continue  # skip low-quality moments once we have enough
                key = (w.media_id, w.scene)
                if w in chosen or (cap is not None and per.get(key, 0) >= cap):
                    continue
                chosen.append(w)
                per[key] = per.get(key, 0) + 1
        used_weights = weights or spec.weights
        weight_names = ', '.join(k for k, v in used_weights.items() if v)
        sens_label = "strict" if sensitivity < 0.3 else "balanced" if sensitivity < 0.7 else "inclusive"
        videos = len({w.media_id for w in cands})
        if videos > 1:
            notes.append(f"Each of the {videos} videos was given its own share of the edit before ranking.")
        notes.append(f"Selected {len(chosen)} of {len(cands)} candidate moments by score "
                     f"({weight_names}), sensitivity: {sens_label}.")
        return chosen
    seeded = _seed_per_media(cands, target, spec, by_score=False)
    if seeded:
        notes.append(f"Sampled {len(seeded)} moments across {len({w.media_id for w in seeded})} videos "
                     "(highlight detection off).")
        return seeded
    chrono = sorted(cands, key=lambda w: (w.media_index, w.start))
    for n in range(1, len(chrono) + 1):
        idx = sorted({round(i * (len(chrono) - 1) / max(1, n - 1)) for i in range(n)}) if n > 1 else [0]
        chosen = [chrono[i] for i in idx]
        if _estimate(chosen, d) >= target:
            break
    notes.append(f"Sampled {len(chosen)} of {len(chrono)} moments evenly across the footage (highlight detection off).")
    return chosen


def arrange(spec: StyleSpec, chosen: list[Window]) -> list[Window]:
    chrono = sorted(chosen, key=lambda w: (w.media_index, w.start))
    merged: list[Window] = []
    for w in chrono:
        prev = merged[-1] if merged else None
        if prev and prev.media_id == w.media_id and abs(prev.end - w.start) < 1e-3 and prev.scene == w.scene:
            merged[-1] = Window(prev.media_id, prev.media_index, prev.scene, prev.start, w.end, prev.bounds,
                                max(prev.score, w.score), prev.feats)
        else:
            merged.append(Window(w.media_id, w.media_index, w.scene, w.start, w.end, w.bounds, w.score, w.feats))
    if spec.order == "hook" and len(merged) > 1:
        best = max(merged, key=lambda w: w.score)
        merged.remove(best)
        merged.insert(0, best)
    return merged


# ------------------------------------------------------------------ clips, focus, timing
def _focus(w: Window, d: dict) -> tuple[float, float]:
    """Subject position (0..1) in the source frame: faces first, else the centre of motion."""
    vis = d["visual"]
    step = vis.get("step", 0.5)
    i0, i1 = int(w.start / step), max(int(w.start / step) + 1, int(math.ceil(w.end / step)))
    pts = [f[:2] for f in vis.get("faces", [])[i0:i1] if f]
    if not pts:
        pts = [c for c in vis.get("centroid", [])[i0:i1] if c]
    if not pts:
        return 0.5, 0.5
    return (round(sum(p[0] for p in pts) / len(pts), 3), round(sum(p[1] for p in pts) / len(pts), 3))


def crop_offset(subject: tuple[float, float], src_w: float, src_h: float, aspect: str) -> tuple[float, float]:
    """Convert a subject position into the crop offset that centres it (mirrors frontend cropOffset)."""
    if aspect == "original":
        return 0.5, 0.5  # output follows the source's own aspect ratio; nothing to crop
    a, b = (int(x) for x in aspect.split(":"))
    out_ar, src_ar = a / b, src_w / max(1.0, src_h)
    fx = fy = 0.5
    if src_ar > out_ar + 1e-3:          # cropping left/right
        r = out_ar / src_ar
        fx = min(1.0, max(0.0, (subject[0] - r / 2) / (1 - r)))
    elif src_ar < out_ar - 1e-3:        # cropping top/bottom
        r = src_ar / out_ar
        fy = min(1.0, max(0.0, (subject[1] - r / 2) / (1 - r)))
    return round(fx, 3), round(fy, 3)


def to_clips(spec: StyleSpec, arranged: list[Window], visuals: dict, data: dict, aspect: str,
             smart_crop: bool) -> tuple[list[dict], dict]:
    clips, bounds = [], {}
    for i, w in enumerate(arranged):
        prev = arranged[i - 1] if i else None
        jump = bool(prev and spec.jump_cuts and prev.media_id == w.media_id and prev.scene == w.scene)
        m = visuals[w.media_id]
        fx, fy = _focus(w, data[w.media_id]) if smart_crop else (0.5, 0.5)
        cid = "c" + uuid.uuid4().hex[:8]
        label = _short_name(m["name"]) if m["kind"] == "image" else f"{_short_name(m['name'])} · S{w.scene + 1}"
        clips.append({"id": cid, "mediaId": w.media_id, "srcStart": round(w.start, 3), "srcEnd": round(w.end, 3),
                      "sceneBreak": not jump, "label": label, "focusX": fx, "focusY": fy,
                      "score": round(w.score, 3), "scoreBreakdown": w.feats, "rejected": False,
                      "boring": w.boring, "boringReason": w.boring_reason})
        bounds[cid] = (w.bounds[0], min(w.bounds[1], float(m["duration"])))
    return clips, bounds


def fit_target(clips: list[dict], transition: dict | None, target: float, min_clip: float,
               notes: list[str] | None = None) -> list[dict]:
    """Shorten the edit to *target* without ever removing a source video: first shave every clip
    proportionally (down to *min_clip*), then drop the weakest clips of videos that still have
    others, and only then report that the target cannot hold all videos."""
    clips = [dict(c) for c in clips]

    def total() -> float:
        return lay.layout(clips, transition)["duration"]

    for _ in range(200):
        excess = total() - target
        if excess <= 0.05 or not clips:
            break
        slack = [max(0.0, (c["srcEnd"] - c["srcStart"]) - min_clip) for c in clips]
        if sum(slack) >= excess:
            for c, sl in zip(clips, slack):
                c["srcEnd"] = round(c["srcEnd"] - excess * sl / sum(slack), 3)
            continue
        counts: dict[str, int] = {}
        for c in clips:
            counts[c["mediaId"]] = counts.get(c["mediaId"], 0) + 1
        droppable = [c for c in clips if counts[c["mediaId"]] > 1]
        if droppable:
            victim = min(droppable, key=lambda c: (c.get("score") or 0.0, -counts[c["mediaId"]]))
            clips.remove(victim)
            continue
        for c in clips:                      # one clip per video left: shave to the minimum and stop
            c["srcEnd"] = round(max(c["srcStart"] + min_clip, c["srcEnd"] - max(0.0, (c["srcEnd"] - c["srcStart"]) - min_clip)), 3)
        if notes is not None and total() - target > 0.05:
            notes.append(f"The {target:.0f}s target is too short to include every video; the edit is "
                         f"{total():.1f}s so no video is dropped.")
        break
    return clips


def beat_sync(clips: list[dict], bounds: dict, transition: dict | None, beat: dict, target: float,
              notes: list[str]) -> list[dict]:
    """Place every cut on the music's beat grid (transition midpoints land on beats)."""
    d = float(transition["duration"]) if transition else 0.0
    unit = beat["period"]
    while unit < max(0.4, 2 * d + 0.15):
        unit *= 2
    b0 = beat["offset"] % unit
    out, s, snapped = [], 0.0, 0
    for k, c in enumerate(clips):
        nxt = clips[k + 1] if k + 1 < len(clips) else None
        overlap = d if (nxt and (nxt["sceneBreak"] or nxt["mediaId"] != c["mediaId"])) else 0.0
        natural = c["srcEnd"] - c["srcStart"]
        lo, hi = bounds[c["id"]]
        m_min = math.ceil((s + 2 * d + 0.1 - b0) / unit)
        m = max(m_min, round((s + natural - overlap / 2 - b0) / unit))
        placed = None
        while m >= m_min:
            boundary = b0 + m * unit
            if boundary > target + 1e-6:
                m -= 1
                continue
            length = boundary - s + overlap / 2
            start = c["srcStart"]
            if start + length > hi:                     # extend backwards inside the scene if needed
                start = max(lo, hi - length)
            if start + length <= hi + 1e-6:
                placed = (boundary, start, length)
                break
            m -= 1
        if placed is None:
            if not out:
                return clips  # cannot sync even the first cut; keep the natural cut
            break
        boundary, start, length = placed
        out.append({**c, "srcStart": round(start, 3), "srcEnd": round(start + length, 3)})
        snapped += 1
        s = boundary - overlap / 2
        if boundary >= target - unit / 2:
            break
    notes.append(f"Cuts synced to the music beat ({60 / beat['period']:.0f} BPM, every "
                 f"{unit / beat['period']:.0f} beat(s)) for {snapped} clip(s).")
    return out


def _dedupe_overlaps(clips: list[dict], visuals: dict, min_clip: float) -> list[dict]:
    """Beat-sync can extend a clip backwards into footage another clip already uses; trim such overlaps
    so the same source seconds never appear twice."""
    out = [dict(c) for c in clips]
    by_media: dict[str, list[dict]] = {}
    for c in out:
        by_media.setdefault(c["mediaId"], []).append(c)
    drop: set[str] = set()
    for mid, group in by_media.items():
        if visuals[mid]["kind"] == "image":
            continue
        group.sort(key=lambda c: c["srcStart"])
        for prev, cur in zip(group, group[1:]):
            if cur["srcStart"] < prev["srcEnd"] - 1e-3:
                cur["srcStart"] = round(prev["srcEnd"], 3)
                if cur["srcEnd"] - cur["srcStart"] < min_clip:
                    drop.add(cur["id"])
    return [c for c in out if c["id"] not in drop]


def _validate_clips(clips: list[dict], visuals: dict) -> None:
    """Fail before rendering (and before the timeline is replaced) on any impossible source range."""
    if not clips:
        raise ValueError("The edit has no clips.")
    for c in clips:
        m = visuals.get(c["mediaId"])
        if m is None:
            raise ValueError(f"Clip {c['id']} refers to an unknown source file.")
        dur = float(m["duration"]) if m["kind"] != "image" else STILL_SECONDS
        if not (0 <= c["srcStart"] < c["srcEnd"] <= dur + 1e-3):
            raise ValueError(f"Invalid source range {c['srcStart']:.2f}-{c['srcEnd']:.2f}s for {m['name']} "
                             f"(length {dur:.2f}s).")


def build_edl(doc, visuals_rows: list[dict], data: dict, music_row: dict | None, beat: dict | None,
              captions: list[dict] | None = None, on_stage=lambda key: None) -> dict:
    """Produce the EDL dict (validated by schemas.Edl at the call site)."""
    st = doc.settings
    visuals = {m["id"]: m for m in visuals_rows}

    # Phase 1: Auto-detect video type and adapt scoring weights (also resolves style == "auto")
    video_type = detect_video_type(data)
    resolved_style = doc.style
    if doc.style == "auto":
        resolved_style = AUTO_STYLE_MAP.get(video_type, "dynamic")
    spec = STYLES[resolved_style]

    notes: list[str] = [f"Style: {spec.name} · {doc.aspect}"]
    if doc.style == "auto":
        notes.append(f"Auto style: picked {spec.name} based on detected content "
                     f"({VIDEO_TYPE_LABELS[video_type]}).")
    transition = ({"type": spec.transition[0], "duration": spec.transition[1]} if st.transitions else None)

    adaptive_w = _adaptive_weights(spec.weights, video_type)
    if video_type != "mixed":
        notes.append(f"Detected content type: {VIDEO_TYPE_LABELS[video_type]}. Scoring weights adapted.")

    # Editing intensity nudges the highlight-sensitivity slider; it never overrides a boring-removal
    # toggle the user set explicitly, since that's a separate, honest on/off control.
    intensity = getattr(st, "intensity", "balanced")
    bonus = INTENSITY_PRESETS.get(intensity, {}).get("sensitivity_bonus", 0.0)
    sensitivity = max(0.0, min(1.0, getattr(st, "highlightSensitivity", 0.5) + bonus))
    if intensity != "balanced":
        notes.append(f"Editing intensity: {intensity}.")

    removed: list[dict] = []
    excluded: list[dict] = []
    cands = candidates(spec, st, visuals_rows, data, notes, weights=adaptive_w, intensity=intensity,
                       sensitivity=sensitivity, removed=removed, excluded=excluded)
    for ex in excluded:
        notes.append(f"{ex['name']} was left out: {ex['reason']}")
    if not cands:
        raise ValueError("No usable footage found: every clip was silent, too short, or removed. "
                         "Try turning off Remove silence.")

    # Phase 2: Boring section removal — filter out consistently low-quality windows
    boring_windows: list[Window] = []
    if getattr(st, "boringRemoval", True):
        cands, boring_windows = mark_boring(cands)
        if boring_windows:
            boring_dur = sum(w.dur for w in boring_windows)
            notes.append(f"Removed {len(boring_windows)} boring section(s) ({boring_dur:.1f}s): "
                         f"low quality across multiple signals.")
        if not cands:
            # All windows were boring — fall back to keeping the best of them
            cands = sorted(boring_windows, key=lambda w: -w.score)[:max(1, len(boring_windows) // 3)]
            for w in cands:
                w.boring = False
                w.boring_reason = None
            boring_windows = [w for w in boring_windows if w not in cands]
            notes.append("All footage scored as boring; kept the top-scoring sections.")

    usable = sum(w.dur for w in cands)
    target = float(st.targetDuration) if st.targetDuration else auto_target(spec, usable)
    n_videos = len({w.media_id for w in cands})
    floor_needed = n_videos * spec.win_min
    conflict = None
    if n_videos > 1 and target < floor_needed:
        notes.append(f"The {target:.0f}s target is shorter than the ~{floor_needed:.0f}s needed to show all "
                     f"{n_videos} videos; the edit will run a little longer so none is dropped.")
        conflict = {"requested": round(target, 1), "suggested": round(floor_needed, 1), "videos": n_videos,
                    "message": f"{target:.0f}s is too short to include all {n_videos} videos. {floor_needed:.0f}s is the "
                               "shortest that keeps every video."}
        target = floor_needed
    if st.targetDuration and st.targetDuration > usable + 0.5:
        notes.append(f"Only {usable:.1f}s of usable footage; the result is shorter than the {st.targetDuration:.0f}s "
                     "target.")
    d = transition["duration"] if transition else 0.0
    chosen = select(spec, cands, target, st.highlightDetection, d, notes,
                    sensitivity=sensitivity, weights=adaptive_w)
    on_stage("decisions")
    arranged = arrange(spec, chosen)
    if spec.order == "hook" and len(arranged) > 1:
        notes.append("Opened with the highest-scoring moment as a hook.")
    clips, bounds = to_clips(spec, arranged, visuals, data, doc.aspect, st.smartCrop)
    if st.smartCrop:
        moved = sum(1 for c in clips if crop_offset((c["focusX"], c["focusY"]), visuals[c["mediaId"]]["width"],
                                                    visuals[c["mediaId"]]["height"], doc.aspect) != (0.5, 0.5))
        if moved:
            notes.append(f"Smart crop follows faces or motion in {moved} clip(s).")
    music = None
    if music_row is not None:
        music = {"mediaId": music_row["id"], "volume": st.musicVolume,
                 "duck": any(visuals[c["mediaId"]]["has_audio"] for c in clips)}
    used_beat = None
    if music and st.beatSync and resolved_style in ("dynamic", "energetic"):
        if beat:
            # Beat sync stops at the target and would silently drop trailing videos; widen the
            # target until every source video is still represented.
            need = {c["mediaId"] for c in clips}
            tgt, synced = target, None
            for _ in range(8):
                tmp: list[str] = []
                out_clips = beat_sync(clips, bounds, transition, beat, tgt, tmp)
                if need <= {c["mediaId"] for c in out_clips}:
                    synced = out_clips
                    notes.extend(tmp)
                    break
                tgt += max(0.5, beat["period"])
            if synced is not None:
                clips = synced
                used_beat = beat["period"]
            else:
                notes.append("Beat sync skipped so that every video stays in the edit.")
                clips = fit_target(clips, transition, target, spec.win_min * 0.5, notes)
        else:
            notes.append("Beat sync skipped: no steady beat detected in the music.")
            clips = fit_target(clips, transition, target, spec.win_min * 0.5, notes)
    else:
        clips = fit_target(clips, transition, target, spec.win_min * 0.5, notes)
    clips = _dedupe_overlaps(clips, visuals, spec.win_min * 0.5)
    _validate_clips(clips, visuals)
    per_video: dict[str, float] = {}
    for c in clips:
        per_video[c["mediaId"]] = per_video.get(c["mediaId"], 0.0) + c["srcEnd"] - c["srcStart"]
    if len(visuals) > 1:
        notes.append("Per video: " + ", ".join(f"{visuals[k]['name']} {v:.1f}s" for k, v in per_video.items()) + ".")
    lt = lay.layout(clips, transition)
    if transition and lt["transition"] == 0 and len(clips) > 1:
        notes.append("Transitions skipped: clips are too short to blend.")
    notes.append(f"{len(clips)} clips, {lt['duration']:.1f}s total.")
    look = st.look or spec.look
    cap_preset = getattr(st, "captionPreset", None) or STYLE_CAPTION_PRESET.get(resolved_style, "classic")
    template_rec, title_specs = None, []
    tpl = templates.get(getattr(doc, "template", None))
    if tpl:
        template_rec, title_specs = templates.lay_out(tpl, clips, lt["duration"])
        notes.append(f"Template: {tpl['name']} ({len(template_rec['sections'])} sections).")
    titles = [{"id": "t" + uuid.uuid4().hex[:8], **t} for t in title_specs]
    return {
        "version": 1, "style": doc.style, "aspect": doc.aspect, "fit": "crop" if st.smartCrop else "blur",
        "clips": clips, "transition": transition, "look": look, "music": music,
        "captions": captions or [], "captionStyle": dict(CAPTION_PRESETS[cap_preset]), "burnCaptions": st.burnCaptions,
        "titles": titles, "template": template_rec, "conflict": conflict,
        "audioClips": ([{"id": "a" + uuid.uuid4().hex[:7], "mediaId": music["mediaId"], "kind": "music", "start": 0.0, "trimIn": 0.0,
                         "duration": None, "volume": music["volume"], "fadeIn": 0.0, "fadeOut": 0.0, "loop": True,
                         "duck": music["duck"]}] if music else []),
        "markers": [],
        "audio": {"normalize": st.normalizeAudio, "lufs": spec.lufs, "clean": spec.clean_audio, "fades": spec.fades},
        "beat": used_beat, "notes": notes, "videoType": video_type, "removed": removed, "excluded": excluded,
        "resolvedStyle": resolved_style if doc.style == "auto" else None,
    }
