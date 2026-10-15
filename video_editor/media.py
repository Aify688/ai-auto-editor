"""Editor media preparation: low-res proxy, thumbnail strip, waveform peaks.

Everything is cached on disk by content id so re-opening a project is instant.
Proxies live under static/ so the browser-side timeline can play them
(Streamlit static serving: /app/static/...).
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

from . import analysis, ffmpeg_ops

ROOT = Path(__file__).resolve().parent.parent
MEDIA_DIR = ROOT / "media"            # persistent imports
STATIC_DIR = ROOT / "static" / "proxy"
URL_PREFIX = "/app/static/proxy"
THUMB_H = 54
PEAK_STEP = 0.1


def content_id(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
    h.update(str(path.stat().st_size).encode())
    return h.hexdigest()[:12]


def import_file(src: Path, name: str | None = None) -> Path:
    """Copy an upload into the persistent media dir (idempotent by content)."""
    MEDIA_DIR.mkdir(exist_ok=True)
    cid = content_id(src)
    dest = MEDIA_DIR / f"{cid}_{Path(name or src.name).name}"
    if not dest.exists():
        shutil.copy2(src, dest)
    return dest


def ingest(path: Path) -> dict:
    """Return editor metadata for a source clip, generating cached assets as needed."""
    path = Path(path)
    info = ffmpeg_ops.probe_video(path)
    cid = content_id(path)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    proxy = STATIC_DIR / f"{cid}_p540.mp4"
    if not proxy.exists():
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-vf", "scale=-2:540,fps=30",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-g", "15", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "64k", "-ac", "2", "-movflags", "+faststart", str(proxy)]
        ffmpeg_ops._run(cmd, f"building preview proxy for {path.name}")
    step = max(0.5, round(info.duration / 80, 2))
    count = max(1, int(math.ceil(info.duration / step)))
    tile_w = max(2, int(round(THUMB_H * info.width / max(1, info.height) / 2)) * 2)
    sprite = STATIC_DIR / f"{cid}_t.jpg"
    if not sprite.exists():
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-an", "-vf",
               f"fps=1/{step},scale={tile_w}:{THUMB_H},tile={count}x1", "-frames:v", "1", "-q:v", "6", str(sprite)]
        ffmpeg_ops._run(cmd, f"building thumbnails for {path.name}")
    peaks_file = STATIC_DIR / f"{cid}_w.json"
    if peaks_file.exists():
        peaks = json.loads(peaks_file.read_text())
    else:
        raw = analysis.audio_energy(path, PEAK_STEP) if info.has_audio else []
        top = max(raw) if raw else 0.0
        peaks = [round(min(1.0, (r / top) ** 0.6), 2) for r in raw] if top > 0 else []
        peaks_file.write_text(json.dumps(peaks))
    return {"id": cid, "path": str(path), "name": path.name.split("_", 1)[-1], "duration": info.duration,
            "w": info.width, "h": info.height, "has_audio": info.has_audio, "fps": info.fps,
            "proxy_url": f"{URL_PREFIX}/{cid}_p540.mp4", "sprite_url": f"{URL_PREFIX}/{cid}_t.jpg",
            "sprite": {"step": step, "count": count, "tile_w": tile_w, "tile_h": THUMB_H},
            "peaks": peaks, "peak_step": PEAK_STEP}


def audio_preview_url(path: Path) -> str:
    """Copy a music file to static so the browser timeline can preview it."""
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    dest = STATIC_DIR / f"a_{content_id(path)}{Path(path).suffix.lower()}"
    if not dest.exists():
        shutil.copy2(path, dest)
    return f"{URL_PREFIX}/{dest.name}"
