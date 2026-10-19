"""Text/graphic overlays rendered with Pillow.

This FFmpeg build has neither libass (`subtitles`) nor `drawtext`, so captions
and graphics are drawn as transparent PNGs and composited with `overlay`.
All items are merged into ONE overlay track (a concat-demuxer image list), so
the number of FFmpeg inputs stays constant however many cues exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

def hex_to_rgba(value: str, alpha: int = 255) -> tuple:
    """Parse '#RRGGBB' (or 'RRGGBB') into an (r, g, b, a) tuple; falls back to white."""
    try:
        h = (value or "").lstrip("#")
        if len(h) != 6:
            raise ValueError
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)
    except (ValueError, TypeError):
        return (255, 255, 255, alpha)


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


FONT_FAMILIES: dict[str, dict[str, list[str]]] = {
    "Arial": {"normal": ["/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/arial.ttf",
                         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
              "bold": ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf",
                       "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]},
    "Georgia": {"normal": ["/System/Library/Fonts/Supplemental/Georgia.ttf", "C:/Windows/Fonts/georgia.ttf"],
                "bold": ["/System/Library/Fonts/Supplemental/Georgia Bold.ttf", "C:/Windows/Fonts/georgiab.ttf"]},
    "Times New Roman": {"normal": ["/System/Library/Fonts/Supplemental/Times New Roman.ttf", "C:/Windows/Fonts/times.ttf"],
                        "bold": ["/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf", "C:/Windows/Fonts/timesbd.ttf"]},
    "Courier New": {"normal": ["/System/Library/Fonts/Supplemental/Courier New.ttf", "C:/Windows/Fonts/cour.ttf"],
                    "bold": ["/System/Library/Fonts/Supplemental/Courier New Bold.ttf", "C:/Windows/Fonts/courbd.ttf"]},
    "Trebuchet MS": {"normal": ["/System/Library/Fonts/Supplemental/Trebuchet MS.ttf", "C:/Windows/Fonts/trebuc.ttf"],
                     "bold": ["/System/Library/Fonts/Supplemental/Trebuchet MS Bold.ttf", "C:/Windows/Fonts/trebucbd.ttf"]},
    "Comic Sans MS": {"normal": ["/System/Library/Fonts/Supplemental/Comic Sans MS.ttf", "C:/Windows/Fonts/comic.ttf"],
                      "bold": ["/System/Library/Fonts/Supplemental/Comic Sans MS Bold.ttf", "C:/Windows/Fonts/comicbd.ttf"]},
    "Impact": {"normal": ["/System/Library/Fonts/Supplemental/Impact.ttf", "C:/Windows/Fonts/impact.ttf"],
               "bold": ["/System/Library/Fonts/Supplemental/Impact.ttf", "C:/Windows/Fonts/impact.ttf"]},
}


def available_fonts() -> list[dict]:
    """Font families this machine can really render (the rest are not offered, never silently swapped)."""
    out = []
    for fam, weights in FONT_FAMILIES.items():
        if any(Path(p).exists() for p in weights["normal"]):
            out.append({"family": fam, "bold": any(Path(p).exists() for p in weights["bold"])})
    return out


def _font_for(family: str, bold: bool, size: int):
    from PIL import ImageFont

    weights = FONT_FAMILIES.get(family) or FONT_FAMILIES["Arial"]
    for p in weights["bold" if bold else "normal"] + weights["normal"]:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return _font(size)


def text_object_layer(size: tuple[int, int], spec: dict, scale: float = 1.0, alpha: float = 1.0, dy: float = 0.0):
    """Full-frame RGBA with one styled, positioned, rotated text object (see schemas.Title)."""
    from PIL import Image, ImageDraw, ImageFilter

    w, h = size
    fs = max(10, int(h * float(spec.get("size", 0.07))))
    font = _font_for(spec.get("font", "Arial"), spec.get("weight", "bold") == "bold", fs)
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    lines = _wrap(probe, spec["text"], font, int(w * 0.84))[:6] or [""]
    line_h = int(fs * 1.2)
    widths = [probe.textlength(l, font=font) for l in lines]
    block_w, block_h = int(max(widths)) + 1, line_h * len(lines)
    pad = int(fs * 0.55)
    canvas = Image.new("RGBA", (block_w + 2 * pad, block_h + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    bg = spec.get("background") or ""
    if bg:
        r, g, b, _ = hex_to_rgba(bg)
        d.rounded_rectangle([0, 0, canvas.width - 1, canvas.height - 1], radius=int(fs * 0.35),
                            fill=(r, g, b, int(255 * float(spec.get("backgroundOpacity", 0.65)))))
    align = spec.get("align", "center")
    stroke = int(round(float(spec.get("strokeWidth", 0)) * fs))
    fill = hex_to_rgba(spec.get("color", "#FFFFFF"))
    if spec.get("shadow"):
        sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        off = max(2, int(fs * 0.06))
        for i, line in enumerate(lines):
            lx = pad + {"left": 0, "center": (block_w - widths[i]) / 2, "right": block_w - widths[i]}[align]
            sd.text((lx + off, pad + i * line_h + off), line, font=font, fill=(0, 0, 0, 200), stroke_width=stroke,
                    stroke_fill=(0, 0, 0, 200))
        canvas = Image.alpha_composite(canvas, sh.filter(ImageFilter.GaussianBlur(max(1, fs * 0.04))))
        d = ImageDraw.Draw(canvas)
    for i, line in enumerate(lines):
        lx = pad + {"left": 0, "center": (block_w - widths[i]) / 2, "right": block_w - widths[i]}[align]
        kw = {"stroke_width": stroke, "stroke_fill": hex_to_rgba(spec.get("strokeColor", "#000000"))} if stroke else {}
        d.text((lx, pad + i * line_h), line, font=font, fill=fill, **kw)
    op = float(spec.get("opacity", 1.0)) * max(0.0, min(1.0, alpha))
    if op < 0.999:
        canvas.putalpha(canvas.getchannel("A").point(lambda p: int(p * op)))
    rot = float(spec.get("rotation", 0))
    if abs(rot) > 0.05:
        canvas = canvas.rotate(-rot, expand=True, resample=Image.BICUBIC)
    if abs(scale - 1.0) > 1e-3:
        canvas = canvas.resize((max(1, int(canvas.width * scale)), max(1, int(canvas.height * scale))), Image.LANCZOS)
    y = spec.get("y")
    if y is None:
        y = {"top": 0.12, "center": 0.5, "bottom": 0.88}.get(spec.get("position", "center"), 0.5)
    cx, cy = float(spec.get("x", 0.5)) * w, float(y) * h + dy * h
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    layer.paste(canvas, (int(cx - canvas.width / 2), int(cy - canvas.height / 2)))   # no mask: it would square the alpha
    return layer


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
               align_left: bool = False, margin_left: float = 0.06, stroke: bool = True):
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
        if stroke:
            d.text((x, y0 + i * line_h), line, font=font, fill=color,
                   stroke_width=max(2, fs // 14), stroke_fill=(0, 0, 0, 255))
        else:
            d.text((x, y0 + i * line_h), line, font=font, fill=color)
    return img


def caption_layer(size: tuple[int, int], words: list[str], active: int | None = None, *, anchor: str = "bottom",
                  font_scale: float = 0.05, margin: float = 0.09, box: bool = True, stroke: bool = True,
                  color=(255, 255, 255, 255), highlight=(255, 215, 0, 255), outline=(0, 0, 0, 255),
                  scale: float = 1.0, alpha: float = 1.0):
    """Full-frame RGBA caption drawn word by word: word *active* is drawn in the highlight colour
    (karaoke), the block can be scaled about its centre (pop/zoom) and faded (alpha)."""
    from PIL import Image, ImageDraw

    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fs = max(14, int(h * font_scale)) if w >= h else max(14, int(w * font_scale))
    font = _font(fs)
    space = d.textlength(" ", font=font)
    max_w = int(w * 0.84)
    lines: list[list[tuple[int, str]]] = [[]]
    cur_w = 0.0
    for i, word in enumerate(words):
        ww = d.textlength(word, font=font)
        add = ww + (space if lines[-1] else 0)
        if lines[-1] and cur_w + add > max_w:
            lines.append([])
            cur_w = 0.0
            add = ww
        lines[-1].append((i, word))
        cur_w += add
    lines = lines[:4]
    line_h = int(fs * 1.25)
    block_h = line_h * len(lines)
    if anchor == "top":
        y0 = int(h * margin)
    elif anchor == "center":
        y0 = (h - block_h) // 2
    else:
        y0 = h - int(h * margin) - block_h

    def line_width(line):
        return sum(d.textlength(t, font=font) for _, t in line) + space * max(0, len(line) - 1)

    if box and lines and lines[0]:
        widest = max(line_width(l) for l in lines)
        x0 = int((w - widest) / 2)
        pad = int(fs * 0.4)
        d.rounded_rectangle([x0 - pad, y0 - pad, x0 + widest + pad, y0 + block_h + pad // 2],
                            radius=pad, fill=(0, 0, 0, 170))
    for li, line in enumerate(lines):
        x = (w - line_width(line)) / 2
        for idx, text in line:
            fill = highlight if active is not None and idx == active else color
            if stroke:
                d.text((x, y0 + li * line_h), text, font=font, fill=fill, stroke_width=max(2, fs // 14), stroke_fill=outline)
            else:
                d.text((x, y0 + li * line_h), text, font=font, fill=fill)
            x += d.textlength(text, font=font) + space
    if scale != 1.0 or alpha < 1.0:
        box_ = img.getbbox()
        if box_:
            crop = img.crop(box_)
            if abs(scale - 1.0) > 1e-3:
                nw, nh = max(1, int(crop.width * scale)), max(1, int(crop.height * scale))
                crop = crop.resize((nw, nh), Image.LANCZOS)
            if alpha < 1.0:
                crop.putalpha(crop.getchannel("A").point(lambda p: int(p * max(0.0, alpha))))
            cx, cy = (box_[0] + box_[2]) // 2, (box_[1] + box_[3]) // 2
            img = Image.new("RGBA", size, (0, 0, 0, 0))
            img.paste(crop, (cx - crop.width // 2, cy - crop.height // 2))   # no mask: the layer is empty, a mask would square the alpha
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
