"""Text/graphic overlays rendered with Pillow.

This FFmpeg build has neither libass (`subtitles`) nor `drawtext`, so captions
and graphics are drawn as transparent PNGs and composited with `overlay`.
All items are merged into ONE overlay track (a concat-demuxer image list), so
the number of FFmpeg inputs stays constant however many cues exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


@dataclass
class OverlayItem:
    start: float
    end: float
    image: object  # PIL.Image.Image, RGBA, full-frame


def _font(size: int):
    from PIL import ImageFont

    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    try:
        return ImageFont.load_default(size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def text_layer(size: tuple[int, int], text: str, *, anchor: str = "bottom", font_scale: float = 0.045,
               margin_bottom: float = 0.08, box: bool = False, color=(255, 255, 255, 255),
               align_left: bool = False, margin_left: float = 0.06):
    """Return a full-frame RGBA image with `text` wrapped and positioned."""
    from PIL import Image, ImageDraw

    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fs = max(14, int(h * font_scale)) if w >= h else max(14, int(w * font_scale))
    font = _font(fs)
    lines = _wrap(d, text, font, int(w * 0.84))[:4]
    line_h = int(fs * 1.25)
    block_h = line_h * len(lines)
    if anchor == "top":
        y0 = int(h * margin_bottom)
    elif anchor == "center":
        y0 = (h - block_h) // 2
    else:
        y0 = h - int(h * margin_bottom) - block_h
    if box and lines:
        widest = max(d.textlength(l, font=font) for l in lines)
        x0 = int(w * margin_left) if align_left else int((w - widest) / 2)
        pad = int(fs * 0.4)
        d.rounded_rectangle([x0 - pad, y0 - pad, x0 + widest + pad, y0 + block_h + pad // 2],
                            radius=pad, fill=(0, 0, 0, 170))
    for i, line in enumerate(lines):
        tw = d.textlength(line, font=font)
        x = int(w * margin_left) if align_left else int((w - tw) / 2)
        d.text((x, y0 + i * line_h), line, font=font, fill=color,
               stroke_width=max(2, fs // 14), stroke_fill=(0, 0, 0, 255))
    return img


def build_overlay_track(items: list[OverlayItem], size: tuple[int, int], total: float,
                        work_dir: Path) -> Path | None:
    """Composite all items onto one timeline and write a concat list file.

    Returns the path of the concat list (use with `-f concat -safe 0`), or None
    if there is nothing to draw.
    """
    from PIL import Image

    items = [i for i in items if i.end > i.start and i.start < total]
    if not items:
        return None
    cuts = sorted({0.0, total, *[min(max(i.start, 0.0), total) for i in items],
                   *[min(max(i.end, 0.0), total) for i in items]})
    blank = work_dir / "ov_blank.png"
    Image.new("RGBA", size, (0, 0, 0, 0)).save(blank)
    lines, cache = [], {}
    last_file = blank
    for a, b in zip(cuts, cuts[1:]):
        if b - a < 1e-3:
            continue
        mid = (a + b) / 2
        active = tuple(idx for idx, it in enumerate(items) if it.start <= mid < it.end)
        if not active:
            f = blank
        elif active in cache:
            f = cache[active]
        else:
            comp = Image.new("RGBA", size, (0, 0, 0, 0))
            for idx in active:
                comp = Image.alpha_composite(comp, items[idx].image)
            f = work_dir / f"ov_{len(cache):04d}.png"
            comp.save(f)
            cache[active] = f
        lines.append(f"file '{f}'\nduration {b - a:.3f}\n")
        last_file = f
    lines.append(f"file '{last_file}'\n")  # concat demuxer ignores the last duration
    lst = work_dir / "overlay_track.txt"
    lst.write_text("".join(lines))
    return lst
