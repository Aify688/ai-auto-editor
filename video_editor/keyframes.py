"""Keyframe animation for one clip: scale, position, rotation and opacity over the clip's own output time.

A keyframe is {"t": seconds into the clip (after speed), "scale", "x", "y", "rotation", "opacity", "ease"}.
x and y are fractions of the frame (0 = centred); `ease` shapes the move from this keyframe to the next.
The frontend preview (frontend/src/lib/keyframes.ts) interpolates the same way.
"""
from __future__ import annotations

PROPS = ("scale", "x", "y", "rotation", "opacity")
DEFAULTS = {"scale": 1.0, "x": 0.0, "y": 0.0, "rotation": 0.0, "opacity": 1.0}
LIMITS = {"scale": (0.1, 5.0), "x": (-1.0, 1.0), "y": (-1.0, 1.0), "rotation": (-360.0, 360.0), "opacity": (0.0, 1.0)}


def normalize(raw: list | None, max_t: float | None = None) -> list[dict]:
    """Sorted, clamped, de-duplicated keyframes; anything malformed is dropped."""
    out: dict[float, dict] = {}
    for k in raw or []:
        try:
            t = round(max(0.0, float(k["t"])), 3)
            if max_t is not None:
                t = min(t, round(max_t, 3))
            kf = {"t": t, "ease": "smooth" if k.get("ease") == "smooth" else "linear"}
            for p in PROPS:
                lo, hi = LIMITS[p]
                kf[p] = round(min(hi, max(lo, float(k.get(p, DEFAULTS[p])))), 4)
        except (KeyError, TypeError, ValueError):
            continue
        out[t] = kf
    return [out[t] for t in sorted(out)]


def value_at(kfs: list[dict], prop: str, t: float) -> float:
    if not kfs:
        return DEFAULTS[prop]
    if t <= kfs[0]["t"]:
        return kfs[0][prop]
    for a, b in zip(kfs, kfs[1:]):
        if t < b["t"]:
            p = (t - a["t"]) / (b["t"] - a["t"])
            if a.get("ease") == "smooth":
                p = p * p * (3 - 2 * p)
            return a[prop] + (b[prop] - a[prop]) * p
    return kfs[-1][prop]


def _expr(kfs: list[dict], prop: str, var: str) -> str:
    """Piecewise expression for FFmpeg, in time variable `var`."""
    if all(abs(k[prop] - kfs[0][prop]) < 1e-9 for k in kfs):
        return f"{kfs[0][prop]:.5f}"
    expr = f"{kfs[-1][prop]:.5f}"
    for a, b in reversed(list(zip(kfs, kfs[1:]))):
        p = f"(({var}-{a['t']:.4f})/{b['t'] - a['t']:.4f})"
        if a.get("ease") == "smooth":
            p = f"({p}*{p}*(3-2*{p}))"
        seg = f"({a[prop]:.5f}+({b[prop] - a[prop]:.5f})*{p})"
        expr = f"if(lt({var},{b['t']:.4f}),{seg},{expr})"
    return f"if(lt({var},{kfs[0]['t']:.4f}),{kfs[0][prop]:.5f},{expr})"


def is_animated(kfs: list[dict]) -> bool:
    return bool(kfs) and any(
        abs(k[p] - DEFAULTS[p]) > 1e-9 for k in kfs for p in PROPS)


def graph(kfs: list[dict], src: str, dst: str, w: int, h: int, fps: int, duration: float) -> str:
    """Filter graph turning [src] (w x h) into [dst] with the animation applied."""
    s, x, y = _expr(kfs, "scale", "t"), _expr(kfs, "x", "t"), _expr(kfs, "y", "t")
    r, o = _expr(kfs, "rotation", "t"), _expr(kfs, "opacity", "T")
    animated_opacity = any(abs(k["opacity"] - 1.0) > 1e-9 for k in kfs)
    animated_rotation = any(abs(k["rotation"]) > 1e-9 for k in kfs)
    chain = f"[{src}]format=rgba,scale=w='max(2,trunc(iw*({s})/2)*2)':h='max(2,trunc(ih*({s})/2)*2)':eval=frame"
    if animated_rotation:
        chain += f",rotate=a='({r})*PI/180':ow='hypot(iw,ih)':oh='hypot(iw,ih)':c=black@0:bilinear=1"
    if animated_opacity:
        chain += f",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*({o})'"
    chain += "[kfg]"
    base = f"color=c=black:s={w}x{h}:r={fps}:d={duration:.3f},format=rgba[kfbase]"
    over = (f"[kfbase][kfg]overlay=x='(W-w)/2+({x})*W':y='(H-h)/2+({y})*H':eval=frame:shortest=1,"
            f"format=yuv420p,setsar=1[{dst}]")
    return f"{chain};{base};{over}"
