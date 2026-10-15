"""Rule-based automatic editing: analysis results + style -> edit decision list (EDL).

Everything here is deterministic signal processing and explicit rules; no generative model.
Pipeline:  candidates (scenes ∩ non-silent audio, split into style-length windows)
        -> score (motion, audio activity, sharpness, faces, steadiness; per-style weights)
        -> select (highlights with a per-scene repetition cap, or even sampling)
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
from .media import STILL_SECONDS


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
]}

PAUSE_PAD = 0.12


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
def candidates(spec: StyleSpec, settings, visuals: list[dict], data: dict, notes: list[str]) -> list[Window]:
    norms = {
        "motion": _p95([v for d in data.values() for v in d["visual"].get("motion", [])]),
        "sharp": _p95([v for d in data.values() for v in d["visual"].get("sharpness", [])]),
        "audio": _p95([v for d in data.values() for v in d["audio"].get("energy", [])]),
    }
    out: list[Window] = []
    removed_total = 0.0
    min_piece = spec.min_piece
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
        active_ratio = 1 - sum(min(b, dur) - a for a, b in silences) / dur if dur else 1
        use_silence = settings.removeSilence and m["has_audio"] and silences and 0.15 <= active_ratio <= 0.97
        cuts = [(a + PAUSE_PAD, b - PAUSE_PAD) for a, b in silences if b - a > 2 * PAUSE_PAD] if use_silence else []
        for si, (sa, sb) in enumerate(scenes):
            sb = min(sb, dur)
            pieces = _subtract(sa, sb, cuts) if cuts else [(sa, sb)]
            removed_total += (sb - sa) - sum(b - a for a, b in pieces)
            for pa, pb in pieces:
                length = pb - pa
                if length < min_piece:
                    continue
                n = max(1, math.ceil(length / spec.win_max))
                if length / n < spec.win_min and n > 1:
                    n = max(1, int(length // spec.win_min))
                seg = length / n
                for k in range(n):
                    out.append(Window(m["id"], mi, si, round(pa + k * seg, 3), round(pa + (k + 1) * seg, 3),
                                      (sa, sb)))
    if removed_total > 0.05:
        notes.append(f"Removed {removed_total:.1f}s of pauses (silence below {-35} dB).")
    for w in out:
        if w.feats:
            continue
        _score(spec, w, data[w.media_id], norms)
    return out


def _score(spec: StyleSpec, w: Window, d: dict, norms: dict) -> None:
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
    score = sum(spec.weights[k] * f[k] for k in spec.weights)
    if bright is not None and (bright < 0.06 or bright > 0.96):
        score *= 0.5                    # near-black or blown-out frames
    w.feats = {k: round(v, 3) for k, v in f.items()}
    w.score = round(score, 4)


# ------------------------------------------------------------------ selection
def auto_target(spec: StyleSpec, usable: float) -> float:
    return min(usable, max(spec.target_min, min(spec.target_max, usable * spec.target_ratio)))


def _estimate(chosen: list[Window], d: float) -> float:
    return sum(w.dur for w in chosen) - d * max(0, len(chosen) - 1)


def select(spec: StyleSpec, cands: list[Window], target: float, highlight: bool, d: float,
           notes: list[str]) -> list[Window]:
    if not cands:
        return []
    if _estimate(cands, d) <= target + 0.05:
        return list(cands)
    if highlight:
        ranked = sorted(cands, key=lambda w: (-w.score, w.media_index, w.start))
        chosen: list[Window] = []
        per: dict = {}
        for cap in ([spec.per_scene] if spec.per_scene else []) + [None]:
            for w in ranked:
                if _estimate(chosen, d) >= target:
                    break
                key = (w.media_id, w.scene)
                if w in chosen or (cap is not None and per.get(key, 0) >= cap):
                    continue
                chosen.append(w)
                per[key] = per.get(key, 0) + 1
        notes.append(f"Selected {len(chosen)} of {len(cands)} candidate moments by score "
                     f"({', '.join(k for k, v in spec.weights.items() if v)}).")
        return chosen
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
                      "score": round(w.score, 3)})
        bounds[cid] = (w.bounds[0], min(w.bounds[1], float(m["duration"])))
    return clips, bounds


def fit_target(clips: list[dict], transition: dict | None, target: float, min_clip: float) -> list[dict]:
    clips = [dict(c) for c in clips]
    while clips:
        total = lay.layout(clips, transition)["duration"]
        excess = total - target
        if excess <= 0.05:
            break
        last = clips[-1]
        if (last["srcEnd"] - last["srcStart"]) - excess >= min_clip or len(clips) == 1:
            last["srcEnd"] = round(max(last["srcStart"] + min_clip, last["srcEnd"] - excess), 3)
            break
        clips.pop()
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


def build_edl(doc, visuals_rows: list[dict], data: dict, music_row: dict | None, beat: dict | None,
              captions: list[dict] | None = None, on_stage=lambda key: None) -> dict:
    """Produce the EDL dict (validated by schemas.Edl at the call site)."""
    spec = STYLES[doc.style]
    st = doc.settings
    notes: list[str] = [f"Style: {spec.name} · {doc.aspect}"]
    visuals = {m["id"]: m for m in visuals_rows}
    transition = ({"type": spec.transition[0], "duration": spec.transition[1]} if st.transitions else None)
    cands = candidates(spec, st, visuals_rows, data, notes)
    if not cands:
        raise ValueError("No usable footage found: every clip was silent, too short, or removed. "
                         "Try turning off Remove silence.")
    usable = sum(w.dur for w in cands)
    target = float(st.targetDuration) if st.targetDuration else auto_target(spec, usable)
    if st.targetDuration and st.targetDuration > usable + 0.5:
        notes.append(f"Only {usable:.1f}s of usable footage; the result is shorter than the {st.targetDuration:.0f}s "
                     "target.")
    d = transition["duration"] if transition else 0.0
    chosen = select(spec, cands, target, st.highlightDetection, d, notes)
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
    if music and st.beatSync and doc.style == "dynamic":
        if beat:
            clips = beat_sync(clips, bounds, transition, beat, target, notes)
            used_beat = beat["period"]
        else:
            notes.append("Beat sync skipped: no steady beat detected in the music.")
            clips = fit_target(clips, transition, target, spec.win_min * 0.5)
    else:
        clips = fit_target(clips, transition, target, spec.win_min * 0.5)
    lt = lay.layout(clips, transition)
    if transition and lt["transition"] == 0 and len(clips) > 1:
        notes.append("Transitions skipped: clips are too short to blend.")
    notes.append(f"{len(clips)} clips, {lt['duration']:.1f}s total.")
    look = st.look or spec.look
    return {
        "version": 1, "style": doc.style, "aspect": doc.aspect, "fit": "crop" if st.smartCrop else "blur",
        "clips": clips, "transition": transition, "look": look, "music": music,
        "captions": captions or [], "burnCaptions": st.burnCaptions, "titles": [],
        "audio": {"normalize": st.normalizeAudio, "lufs": spec.lufs, "clean": spec.clean_audio, "fades": spec.fades},
        "beat": used_beat, "notes": notes,
    }
