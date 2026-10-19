"""Execution handlers for registry capabilities.

Handler contracts by stage:
  analyze : fn(ctx: PlanCtx, settings) -> None        mutates ctx.segments / ctx.notes
  segment : fn(settings, seg: SegCtx) -> SegFrag      per-clip FFmpeg filter fragments
  master  : fn(settings, m: MasterCtx) -> MasterFrag  whole-program audio chain
  overlay : fn(settings, o: OverlayCtx) -> list[OverlayItem]
  join    : read by the engine (transitions)
Every handler does real work; nothing here is a placeholder.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from . import analysis
from .ffmpeg_ops import ClipInfo
from .overlay import OverlayItem, caption_layer, hex_to_rgba, text_layer, text_object_layer


# ---------------------------------------------------------------- contexts
@dataclass
class Seg:
    clip: int
    start: float
    end: float
    brk: bool = False   # starts a new scene (transitions apply here, not at jump cuts)

    @property
    def dur(self) -> float:
        return self.end - self.start


@dataclass
class PlanCtx:
    clips: list[ClipInfo]
    segments: list[Seg]
    notes: list[str] = field(default_factory=list)
    cues: list[dict] = field(default_factory=list)  # {clip,start,end,text}


@dataclass
class SegCtx:
    width: int
    height: int
    fps: int


@dataclass
class SegFrag:
    vf: list[str] = field(default_factory=list)
    af: list[str] = field(default_factory=list)
    speed: float = 1.0


@dataclass
class MasterCtx:
    duration: float
    has_voice: bool = True


@dataclass
class MasterFrag:
    voice_af: list[str] = field(default_factory=list)   # before music mix
    final_af: list[str] = field(default_factory=list)   # after music mix
    music: dict | None = None
    tracks: list[dict] = field(default_factory=list)   # audio timeline clips (see master_tracks)


@dataclass
class OverlayCtx:
    size: tuple[int, int]
    duration: float
    seg_starts: list[tuple]  # (clip, src_start, src_end, out_start[, rate]); rate = per-clip speed
    speed: float = 1.0


# ---------------------------------------------------------------- analyze
def _subtract(seg: Seg, cuts: list[tuple[float, float]], min_keep: float) -> list[Seg]:
    pieces, pos = [], seg.start
    for a, b in sorted(cuts):
        if b <= pos or a >= seg.end:
            continue
        if a > pos:
            pieces.append((pos, min(a, seg.end)))
        pos = max(pos, b)
    if pos < seg.end:
        pieces.append((pos, seg.end))
    kept = [(a, b) for a, b in pieces if b - a >= min_keep]
    return [Seg(seg.clip, a, b, brk=seg.brk and i == 0) for i, (a, b) in enumerate(kept)]


def remove_pauses(ctx: PlanCtx, s: dict) -> None:
    noise, min_sil, pad, min_keep = s["noise_db"], s["min_pause"], s["padding"], s["min_keep"]
    silences: dict[int, list[tuple[float, float]]] = {}
    removed = 0.0
    out: list[Seg] = []
    for seg in ctx.segments:
        clip = ctx.clips[seg.clip]
        if not clip.has_audio:
            ctx.notes.append(f"Clip {seg.clip} has no audio; pauses were not removed from it.")
            out.append(seg)
            continue
        if seg.clip not in silences:
            raw = analysis.detect_silences(clip.path, noise, min_sil)
            # keep `pad` of each pause so cuts breathe instead of clipping words
            silences[seg.clip] = [(a + pad, b - pad) for a, b in raw if (b - a) > 2 * pad]
        pieces = _subtract(seg, silences[seg.clip], min_keep)
        removed += seg.dur - sum(p.dur for p in pieces)
        out.extend(pieces)
    if not out:
        ctx.notes.append("Pause removal would have removed everything; kept original segments.")
        return
    ctx.segments = out
    ctx.notes.append(f"Removed {removed:.1f}s of pauses (<{noise:.0f} dB for >{min_sil}s).")


def best_moments(ctx: PlanCtx, s: dict) -> None:
    target, win = float(s["target_duration"]), float(s["window"])
    step = 0.5
    scored: list[tuple[float, int, float, float]] = []  # score, clip, start, end
    for ci, clip in enumerate(ctx.clips):
        segs = [g for g in ctx.segments if g.clip == ci]
        if not segs:
            continue
        a = analysis.audio_energy(clip.path, step) if clip.has_audio else []
        v = analysis.visual_activity(clip.path, step)
        amax = max(a) if a else 0.0
        vmax = max(v) if v else 0.0
        per = max(1, int(round(win / step)))
        for seg in segs:
            t = seg.start
            while t < seg.end - 1e-6:
                e = min(t + win, seg.end)
                if e - t >= min(win, seg.dur) - 1e-6:  # full windows only
                    i0, i1 = int(t / step), max(int(t / step) + 1, int(e / step))
                    sa = (sum(a[i0:i1]) / max(1, len(a[i0:i1])) / amax) if amax > 0 and a[i0:i1] else 0.0
                    sv = (sum(v[i0:i1]) / max(1, len(v[i0:i1])) / vmax) if vmax > 0 and v[i0:i1] else 0.0
                    weight_a = 0.6 if a else 0.0
                    scored.append((weight_a * sa + (1 - weight_a) * sv, ci, t, e))
                t += win
    if not scored:
        return
    total = sum(g.dur for g in ctx.segments)
    if target >= total:
        ctx.notes.append("Target duration >= source length; nothing to select.")
        return
    need = max(1, int(math.ceil(target / win)))
    chosen = sorted(scored, key=lambda x: -x[0])[:need]
    hook = max(chosen, key=lambda x: x[0]) if s.get("hook_first") else None
    ordered = sorted(chosen, key=lambda x: (x[1], x[2]))
    if hook is not None:
        ordered.remove(hook)
        ordered.insert(0, hook)
    merged: list[Seg] = []
    for _, ci, a, b in ordered:
        if merged and merged[-1].clip == ci and abs(merged[-1].end - a) < 1e-3:
            merged[-1].end = b
        else:
            merged.append(Seg(ci, a, b, brk=bool(merged)))
    excess = sum(g.dur for g in merged) - target
    if excess > 0.05 and merged:  # trim the tail so the target is hit exactly
        merged[-1].end = max(merged[-1].start + 0.3, merged[-1].end - excess)
    ctx.segments = merged
    ctx.notes.append(
        f"Selected {len(merged)} high-activity moments (audio energy + scene change) "
        f"for ~{target:.0f}s" + ("; strongest moment moved to the start as a hook." if hook else "."))


def transcribe(ctx: PlanCtx, s: dict) -> None:
    from faster_whisper import WhisperModel  # dependency probed by the registry

    model = WhisperModel(s["model"], device="cpu", compute_type="int8")
    for ci, clip in enumerate(ctx.clips):
        if not clip.has_audio:
            continue
        segs, _ = model.transcribe(str(clip.path), vad_filter=True)
        for sg in segs:
            if sg.text.strip():
                ctx.cues.append({"clip": ci, "start": float(sg.start), "end": float(sg.end),
                                 "text": sg.text.strip()})
    ctx.notes.append(f"Transcribed {len(ctx.cues)} caption cues with faster-whisper ({s['model']}).")


# ---------------------------------------------------------------- segment
def _atempo(f: float) -> list[str]:
    chain = []
    while f > 2.0:
        chain.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        chain.append("atempo=0.5")
        f /= 0.5
    chain.append(f"atempo={f:.4f}")
    return chain


def speed(s: dict, seg: SegCtx) -> SegFrag:
    f = float(s["factor"])
    return SegFrag(vf=[f"setpts=PTS/{f:.4f}"], af=_atempo(f), speed=f)


def color_adjust(s: dict, seg: SegCtx) -> SegFrag:
    vf = [f"eq=brightness={s['brightness']}:contrast={s['contrast']}:saturation={s['saturation']}:gamma={s['gamma']}"]
    return SegFrag(vf=vf)


def color_temperature(s: dict, seg: SegCtx) -> SegFrag:
    return SegFrag(vf=[f"colortemperature=temperature={int(s['kelvin'])}"])


LOOKS = {
    "warm": ["colortemperature=temperature=4800", "eq=saturation=1.1:contrast=1.04"],
    "cool": ["colortemperature=temperature=8500", "eq=saturation=1.05"],
    "cinematic": ["eq=contrast=1.12:saturation=0.92:gamma=0.95",
                  "colorbalance=rs=0.04:bs=-0.04:rh=0.03:bh=-0.02", "vignette=PI/6"],
    "vivid": ["eq=contrast=1.08:saturation=1.35"],
    "bw": ["hue=s=0", "eq=contrast=1.1"],
    "faded": ["eq=contrast=0.9:saturation=0.8:brightness=0.03"],
}


def color_look(s: dict, seg: SegCtx) -> SegFrag:
    return SegFrag(vf=list(LOOKS[s["look"]]))


def color_lut(s: dict, seg: SegCtx) -> SegFrag:
    p = str(s["path"]).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return SegFrag(vf=[f"lut3d=file='{p}'"])


def fx_denoise(s: dict, seg: SegCtx) -> SegFrag:
    st = float(s["strength"])
    return SegFrag(vf=[f"hqdn3d={st}:{st * 0.75:.2f}:{st * 1.5:.2f}:{st * 1.1:.2f}"])


def fx_sharpen(s: dict, seg: SegCtx) -> SegFrag:
    return SegFrag(vf=[f"unsharp=5:5:{s['amount']}:5:5:0.0"])


def fx_vignette(s: dict, seg: SegCtx) -> SegFrag:
    return SegFrag(vf=[f"vignette=angle={s['angle']}"])


def fx_punch_in(s: dict, seg: SegCtx) -> SegFrag:
    z = float(s["zoom"])
    return SegFrag(vf=[f"crop=iw/{z}:ih/{z}"])  # centre crop; the resize stage rescales it


# ---------------------------------------------------------------- master
def master_clean(s: dict, m: MasterCtx) -> MasterFrag:
    af = []
    if s["highpass"]:
        af.append("highpass=f=80")
    if s["denoise"]:
        af.append(f"afftdn=nr={s['noise_reduction_db']}:nf=-35")
    return MasterFrag(voice_af=af)


def master_loudnorm(s: dict, m: MasterCtx) -> MasterFrag:
    return MasterFrag(final_af=[f"loudnorm=I={s['target_lufs']}:TP=-1.5:LRA=11"])


def master_fades(s: dict, m: MasterCtx) -> MasterFrag:
    af = []
    if s["fade_in"] > 0:
        af.append(f"afade=t=in:st=0:d={s['fade_in']}")
    if s["fade_out"] > 0:
        st = max(0.0, m.duration - s["fade_out"])
        af.append(f"afade=t=out:st={st:.3f}:d={s['fade_out']}")
    return MasterFrag(final_af=af)


def master_volume(s: dict, m: MasterCtx) -> MasterFrag:
    return MasterFrag(voice_af=[f"volume={s['gain_db']}dB"])


def master_tracks(s: dict, m: MasterCtx) -> MasterFrag:
    """Audio timeline clips: each is {path, volume, duck, start, trim_in, length, fade_in, fade_out, loop, src_len}."""
    tracks = []
    for t in s.get("tracks") or []:
        start = max(0.0, float(t.get("start", 0)))
        if start >= m.duration - 0.02:
            continue
        length = t.get("length")
        length = m.duration - start if length is None else min(float(length), m.duration - start)
        if length < 0.05:
            continue
        tracks.append({"path": t["path"], "volume": max(0.0, min(1.0, float(t.get("volume", 0.35)))),
                       "duck": bool(t.get("duck", True)), "start": start, "trim_in": max(0.0, float(t.get("trim_in", 0))),
                       "length": length, "fade_in": min(float(t.get("fade_in", 0)), length),
                       "fade_out": min(float(t.get("fade_out", 0)), length), "loop": bool(t.get("loop")),
                       "effect": t.get("effect") or "none"})
    return MasterFrag(tracks=tracks)


def master_music(s: dict, m: MasterCtx) -> MasterFrag:
    return MasterFrag(music={"path": s["path"], "volume": float(s["volume"]), "duck": bool(s["duck"])})


# ---------------------------------------------------------------- overlay
def _remap(cue: dict, starts, speed: float) -> list[tuple[float, float]]:
    """Map a source-time cue to output-time spans (cue may straddle cuts)."""
    out = []
    for clip, a, b, o, *rest in starts:
        if clip != cue["clip"]:
            continue
        sp = speed * (rest[0] if rest else 1.0)
        lo, hi = max(a, cue["start"]), min(b, cue["end"])
        if hi - lo > 0.05:
            out.append((o + (lo - a) / sp, o + (hi - a) / sp))
    return out


def _remap_parts(cue: dict, starts, speed: float) -> list[dict]:
    """Like _remap, but also returns the source range and the mapping so words can be placed too."""
    out = []
    for clip, a, b, o, *rest in starts:
        if clip != cue["clip"]:
            continue
        sp = speed * (rest[0] if rest else 1.0)
        lo, hi = max(a, cue["start"]), min(b, cue["end"])
        if hi - lo > 0.05:
            out.append({"out_a": o + (lo - a) / sp, "out_b": o + (hi - a) / sp, "lo": lo, "hi": hi,
                        "map": lambda x, a=a, o=o, sp=sp: o + (x - a) / sp})
    return out


ANIM_SECONDS = {"fade": 0.18, "pop": 0.22, "scale": 0.30}


def _anim_params(kind: str, t: float, dur: float, a: float, b: float) -> tuple[float, float]:
    """(scale, alpha) of a caption at output time t for a cue shown during [a, b]."""
    if kind == "none":
        return 1.0, 1.0
    d_in = min(ANIM_SECONDS.get(kind, 0.2), (b - a) / 2)
    d_out = min(0.12, (b - a) / 4) if kind in ("fade", "scale") else 0.0
    scale, alpha = 1.0, 1.0
    if t < a + d_in:
        p = max(0.0, min(1.0, (t - a) / d_in))
        if kind == "fade":
            alpha = p
        elif kind == "pop":                       # overshoot: 0.6 -> 1.12 -> 1.0
            scale = 0.6 + 0.52 * min(1.0, p / 0.7) if p < 0.7 else 1.12 - 0.12 * (p - 0.7) / 0.3
            alpha = min(1.0, p / 0.4)
        elif kind == "scale":
            scale = 0.88 + 0.12 * p
            alpha = p
    if d_out and t > b - d_out:
        alpha = min(alpha, max(0.0, (b - t) / d_out))
    return scale, alpha


def overlay_captions(s: dict, o: OverlayCtx) -> list[OverlayItem]:
    w, h = o.size
    vertical = h > w
    anchor = s.get("position", "bottom")
    margin = 0.22 if vertical else 0.09  # stay above platform UI (bottom 20-35% on shorts)
    if anchor == "top":
        margin = 0.1 if vertical else 0.06
    color = hex_to_rgba(s.get("color", "#FFFFFF"))
    highlight = hex_to_rgba(s.get("highlight_color", "#FFD700"))
    outline = hex_to_rgba(s.get("outline_color", "#000000"))
    background = s.get("background")  # "box" | "outline" | "none"; falls back to the legacy "box" bool
    box = bool(s["box"]) if background is None else background == "box"
    stroke = True if background is None else background != "none"
    karaoke = bool(s.get("karaoke"))
    anim = s.get("animation", "none")
    upper = bool(s.get("uppercase"))
    fmt = (lambda t: t.upper()) if upper else (lambda t: t)
    fps = 15.0
    items: list[OverlayItem] = []
    for cue in s["cues"]:
        for part in _remap_parts(cue, o.seg_starts, o.speed):
            a, b = part["out_a"], part["out_b"]
            words = [wd for wd in (cue.get("words") or []) if wd["end"] > part["lo"] + 0.02 and wd["start"] < part["hi"] - 0.02]
            if words:
                tokens = [fmt(wd["word"]) for wd in words]
                spans = [(part["map"](max(wd["start"], part["lo"])), part["map"](min(wd["end"], part["hi"]))) for wd in words]
            else:
                tokens, spans = fmt(cue["text"]).split(), []
            if not tokens:
                continue
            cuts = {a, b}
            if karaoke and spans:
                for x, y in spans:
                    cuts.update((min(max(x, a), b), min(max(y, a), b)))
            d_in = min(ANIM_SECONDS.get(anim, 0.0), (b - a) / 2) if anim != "none" else 0.0
            n_in = max(1, int(round(d_in * fps))) if d_in else 0
            cuts.update(a + d_in * k / n_in for k in range(n_in + 1)) if n_in else None
            if anim in ("fade", "scale"):
                d_out = min(0.12, (b - a) / 4)
                cuts.update(b - d_out * k / 2 for k in range(3))
            edges = sorted(c for c in cuts if a - 1e-6 <= c <= b + 1e-6)
            cache: dict = {}
            for t0, t1 in zip(edges, edges[1:]):
                if t1 - t0 < 1e-3:
                    continue
                mid = (t0 + t1) / 2
                active = None
                if karaoke and spans:
                    for i, (x, y) in enumerate(spans):
                        if x <= mid < y:
                            active = i
                            break
                sc, al = _anim_params(anim, mid, b - a, a, b)
                key = (active, round(sc, 2), round(al, 2))
                if key not in cache:
                    cache[key] = caption_layer(o.size, tokens, active, anchor=anchor, font_scale=s["font_scale"],
                                               margin=margin, box=box, stroke=stroke, color=color, highlight=highlight,
                                               outline=outline, scale=sc, alpha=al)
                items.append(OverlayItem(t0, t1, cache[key]))
    return items


def overlay_title(s: dict, o: OverlayCtx) -> list[OverlayItem]:
    a = float(s["start"])
    b = min(o.duration, a + float(s["duration"]))
    if b - a < 0.05:
        return []
    anim = s.get("animation", "none")
    fps = 15.0
    d_in = min(ANIM_SECONDS.get(anim, 0.3 if anim == "slide" else 0.0), (b - a) / 2) if anim != "none" else 0.0
    d_out = min(0.12, (b - a) / 4) if anim in ("fade", "scale", "slide") else 0.0
    cuts = {a, b}
    if d_in:
        n = max(1, int(round(d_in * fps)))
        cuts.update(a + d_in * k / n for k in range(n + 1))
    if d_out:
        cuts.update(b - d_out * k / 2 for k in range(3))
    edges = sorted(c for c in cuts if a - 1e-6 <= c <= b + 1e-6)
    items, cache = [], {}
    for t0, t1 in zip(edges, edges[1:]):
        if t1 - t0 < 1e-3:
            continue
        mid = (t0 + t1) / 2
        kind = "fade" if anim == "slide" else anim
        scale, alpha = _anim_params(kind, mid, b - a, a, b)
        dy = 0.0
        if anim == "slide" and d_in and mid < a + d_in:
            dy = 0.06 * (1 - (mid - a) / d_in)
        key = (round(scale, 2), round(alpha, 2), round(dy, 3))
        if key not in cache:
            cache[key] = text_object_layer(o.size, s, scale, alpha, dy)
        items.append(OverlayItem(t0, t1, cache[key]))
    return items


def overlay_lower_third(s: dict, o: OverlayCtx) -> list[OverlayItem]:
    text = s["name"] + (f"\n{s['subtitle']}" if s.get("subtitle") else "")
    first, _, rest = text.partition("\n")
    from PIL import Image

    base = text_layer(o.size, first, anchor="bottom", font_scale=0.05, margin_bottom=0.20 if rest else 0.15,
                      box=True, align_left=True)
    if rest:
        sub = text_layer(o.size, rest, anchor="bottom", font_scale=0.034, margin_bottom=0.15,
                         box=True, align_left=True)
        base = Image.alpha_composite(base, sub)
    st = float(s["start"])
    return [OverlayItem(st, min(o.duration, st + float(s["duration"])), base)]


def overlay_watermark(s: dict, o: OverlayCtx) -> list[OverlayItem]:
    from PIL import Image

    w, h = o.size
    logo = Image.open(s["path"]).convert("RGBA")
    tw = int(w * float(s["scale"]))
    logo = logo.resize((tw, max(1, int(logo.height * tw / logo.width))))
    alpha = logo.getchannel("A").point(lambda p: int(p * float(s["opacity"])))
    logo.putalpha(alpha)
    margin = int(min(w, h) * 0.04)
    pos = {"top_left": (margin, margin), "top_right": (w - tw - margin, margin),
           "bottom_left": (margin, h - logo.height - margin),
           "bottom_right": (w - tw - margin, h - logo.height - margin)}[s["position"]]
    canvas = Image.new("RGBA", o.size, (0, 0, 0, 0))
    canvas.paste(logo, pos, logo)
    return [OverlayItem(0.0, o.duration, canvas)]
