"""Per-clip video effects and colour filters (the CapCut-style library).

A clip carries `effects: [{"id", "amount"}]` (amount 0..1, applied in order) and `filter: {"id", "strength"}`.
`fx_graph` turns them into an FFmpeg filter graph fragment. The frontend (lib/effects.ts) lists the same ids
and approximates them with CSS for the live preview.
"""
from __future__ import annotations

# id -> function(amount) -> list of FFmpeg video filters (kept size-preserving so later stages see the same frame)
def _a(amount: float, lo: float, hi: float) -> float:
    return lo + (hi - lo) * max(0.0, min(1.0, amount))


EFFECTS: dict[str, dict] = {
    "blur": {"label": "Blur", "f": lambda a: [f"gblur=sigma={_a(a, 1, 24):.2f}"]},
    "sharpen": {"label": "Sharpen", "f": lambda a: [f"unsharp=5:5:{_a(a, 0.3, 2.5):.2f}:5:5:0"]},
    "vignette": {"label": "Vignette", "f": lambda a: [f"vignette=angle={_a(a, 0.25, 0.95):.3f}"]},
    "grain": {"label": "Film grain", "f": lambda a: [f"noise=alls={_a(a, 6, 45):.0f}:allf=t"]},
    "glitch": {"label": "RGB glitch", "f": lambda a: [
        f"rgbashift=rh={-_a(a, 2, 14):.0f}:bh={_a(a, 2, 14):.0f}:gv={_a(a, 0, 4):.0f}"]},
    "pixelate": {"label": "Pixelate", "f": lambda a: [f"pixelize=w={int(_a(a, 6, 40))}:h={int(_a(a, 6, 40))}"]},
    "mono": {"label": "Black & white", "f": lambda a: ["hue=s=0"]},
    "sepia": {"label": "Sepia", "f": lambda a: [
        "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131"]},
    "invert": {"label": "Invert", "f": lambda a: ["negate"]},
    "flip_h": {"label": "Flip horizontal", "f": lambda a: ["hflip"]},
    "flip_v": {"label": "Flip vertical", "f": lambda a: ["vflip"]},
    "shake": {"label": "Shake", "f": lambda a: [
        f"crop=w='iw*{1 - _a(a, 0.04, 0.12):.3f}':h='ih*{1 - _a(a, 0.04, 0.12):.3f}'"
        f":x='(iw-ow)/2*(1+sin(t*{_a(a, 25, 60):.1f}))':y='(ih-oh)/2*(1+cos(t*{_a(a, 31, 70):.1f}))'",
        f"scale=w='trunc(iw/{1 - _a(a, 0.04, 0.12):.3f}/2)*2':h='trunc(ih/{1 - _a(a, 0.04, 0.12):.3f}/2)*2'"]},
    "dream": {"label": "Dream glow", "f": lambda a: [
        f"gblur=sigma={_a(a, 3, 12):.1f}", f"eq=brightness={_a(a, 0.02, 0.08):.3f}:saturation=1.15"]},
}

# Colour filters (per clip, with strength). These are looks beyond the project-wide grade in skills.LOOKS.
FILTERS: dict[str, dict] = {
    "warm": {"label": "Warm", "f": ["colortemperature=temperature=4800", "eq=saturation=1.1:contrast=1.04"]},
    "cool": {"label": "Cool", "f": ["colortemperature=temperature=8500", "eq=saturation=1.05"]},
    "cinematic": {"label": "Cinematic", "f": ["eq=contrast=1.12:saturation=0.92:gamma=0.95",
                                             "colorbalance=rs=0.04:bs=-0.04:rh=0.03:bh=-0.02"]},
    "vivid": {"label": "Vivid", "f": ["eq=contrast=1.08:saturation=1.35"]},
    "bw": {"label": "B&W", "f": ["hue=s=0", "eq=contrast=1.1"]},
    "faded": {"label": "Faded", "f": ["eq=contrast=0.9:saturation=0.8:brightness=0.03"]},
    "noir": {"label": "Noir", "f": ["hue=s=0", "eq=contrast=1.45:brightness=-0.04", "vignette=angle=0.6"]},
    "sunset": {"label": "Sunset", "f": ["colorbalance=rs=0.12:gs=-0.02:bs=-0.1:rm=0.08:bm=-0.06", "eq=saturation=1.2"]},
    "teal_orange": {"label": "Teal & orange", "f": ["colorbalance=rs=-0.08:bs=0.1:rh=0.12:bh=-0.1", "eq=contrast=1.1:saturation=1.15"]},
    "retro": {"label": "Retro", "f": ["colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
                                      "eq=contrast=0.95:brightness=0.02", "vignette=angle=0.5"]},
    "fresh": {"label": "Fresh", "f": ["eq=brightness=0.04:saturation=1.25:contrast=1.04", "colortemperature=temperature=7000"]},
    "matte": {"label": "Matte", "f": ["curves=all='0/0.08 1/0.92'", "eq=saturation=0.9"]},
}

MAX_EFFECTS = 6


def normalize(effects: list | None, flt: dict | None) -> tuple[list[dict], dict | None]:
    """Drop unknown ids, clamp amounts."""
    out = []
    for e in (effects or [])[:MAX_EFFECTS]:
        try:
            if e["id"] in EFFECTS:
                out.append({"id": e["id"], "amount": round(max(0.0, min(1.0, float(e.get("amount", 0.5)))), 3)})
        except (KeyError, TypeError, ValueError):
            continue
    f = None
    try:
        if flt and flt["id"] in FILTERS:
            f = {"id": flt["id"], "strength": round(max(0.0, min(1.0, float(flt.get("strength", 1.0)))), 3)}
    except (KeyError, TypeError, ValueError):
        f = None
    return out, f


def fx_graph(src: str, dst: str, effects: list[dict], flt: dict | None) -> str:
    """Graph fragment [src] -> [dst] applying the colour filter (blended by strength) then the effects in order."""
    parts, cur = [], src
    if flt:
        chain = ",".join(FILTERS[flt["id"]]["f"])
        s = flt["strength"]
        if s >= 0.999:
            parts.append(f"[{cur}]{chain}[flt]")
        else:
            parts.append(f"[{cur}]split[fa][fb];[fb]{chain}[fc];[fa][fc]blend=all_mode=normal:all_opacity={s:.3f}[flt]")
        cur = "flt"
    for i, e in enumerate(effects):
        chain = ",".join(EFFECTS[e["id"]]["f"](e["amount"]))
        # effects that depend on their amount keep full strength at 1; `mono`, `sepia`, `invert` blend by amount
        if e["id"] in ("mono", "sepia", "invert") and e["amount"] < 0.999:
            parts.append(f"[{cur}]split[ea{i}][eb{i}];[eb{i}]{chain}[ec{i}];[ea{i}][ec{i}]blend=all_mode=normal:all_opacity={max(0.05, e['amount']):.3f}[fx{i}]")
        else:
            parts.append(f"[{cur}]{chain}[fx{i}]")
        cur = f"fx{i}"
    parts.append(f"[{cur}]null[{dst}]")
    return ";".join(parts)
