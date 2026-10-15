"""Media library: upload validation, ffprobe metadata, thumbnails, proxies, waveforms.

Files live under data/projects/<pid>/media (originals) and .../cache (derived assets).
The database stores paths relative to DATA_DIR, never file contents.
"""
from __future__ import annotations

import json
import math
import shutil
import time
import uuid
from pathlib import Path
from typing import BinaryIO

from video_editor import analysis
from video_editor.ffmpeg_ops import _run, run_process

from .. import config, db

PROXY_SHORT_EDGE = 540
THUMB_W = 320
SPRITE_H = 56
PEAK_STEP = 0.1
STILL_SECONDS = 15.0
CHUNK = 1 << 20


class MediaError(ValueError):
    pass


class TooLarge(MediaError):
    pass


def rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(config.DATA_DIR))


def absolute(relpath: str) -> Path:
    return config.DATA_DIR / relpath


def url_for(path: Path) -> str:
    return "/files/" + rel(path)


def _row(m: dict) -> dict:
    return {
        "id": m["id"], "projectId": m["project_id"], "name": m["name"], "kind": m["kind"], "ext": m["ext"],
        "size": m["size"], "status": m["status"], "error": m["error"], "position": m["position"],
        "duration": m["duration"], "width": m["width"], "height": m["height"], "fps": m["fps"],
        "hasAudio": bool(m["has_audio"]), "info": {k: v for k, v in db.loads(m["info"], {}).items()
                                                  if not k.startswith("_")},
    }


def list_media(pid: str) -> list[dict]:
    return [_row(m) for m in db.query("SELECT * FROM media WHERE project_id=? ORDER BY position, created_at", (pid,))]


def get_row(mid: str) -> dict | None:
    return db.one("SELECT * FROM media WHERE id=?", (mid,))


def get(mid: str) -> dict | None:
    m = get_row(mid)
    return _row(m) if m else None


def render_path(mid: str) -> Path:
    """File the render engine should read for this media (original video or generated still clip)."""
    m = get_row(mid)
    if m is None:
        raise MediaError(f"Media {mid} no longer exists.")
    info = db.loads(m["info"], {})
    if m["status"] != "ready":
        raise MediaError(f"{m['name']} is not ready ({m['status']}).")
    return absolute(info.get("_renderPath") or m["path"])


def proxy_path(mid: str) -> Path | None:
    m = get_row(mid)
    info = db.loads(m["info"], {}) if m else {}
    return absolute(info["_proxyPath"]) if info.get("_proxyPath") else None


# ------------------------------------------------------------------ probing
def ffprobe(path: Path) -> dict:
    res = run_process(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    if res.returncode != 0:
        msg = (res.stderr or "").strip().replace(str(path), path.name).splitlines()
        reason = msg[-1].split(": ", 1)[-1] if msg else ""
        raise MediaError("Could not read this file" + (f" ({reason})." if reason else ". It may be corrupt."))
    return json.loads(res.stdout or "{}")


def _fps(raw: str | None) -> float | None:
    try:
        num, _, den = (raw or "").partition("/")
        val = float(num) / float(den or 1)
        return round(val, 3) if 0 < val < 1000 else None
    except (ValueError, ZeroDivisionError):
        return None


def _rotation(stream: dict) -> int:
    rot = stream.get("tags", {}).get("rotate")
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = sd["rotation"]
    try:
        return int(float(rot or 0)) % 360
    except ValueError:
        return 0


def describe(path: Path, kind: str) -> dict:
    """Validate the file's real content against its declared kind and extract metadata."""
    data = ffprobe(path)
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(fmt.get("duration") or (video or audio or {}).get("duration") or 0) or None
    meta: dict = {"duration": duration, "width": None, "height": None, "fps": None, "has_audio": bool(audio),
                  "videoCodec": (video or {}).get("codec_name"), "audioCodec": (audio or {}).get("codec_name"),
                  "bitrate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None}
    if kind in ("video", "image"):
        if video is None:
            raise MediaError(f"No {'picture' if kind == 'image' else 'video stream'} found in this file.")
        w, h = int(video.get("width") or 0), int(video.get("height") or 0)
        if _rotation(video) in (90, 270):
            w, h = h, w
        if not w or not h:
            raise MediaError("Could not determine the frame size.")
        meta.update(width=w, height=h)
    if kind == "video":
        if not duration or duration < 0.2:
            raise MediaError("Video is empty or shorter than 0.2 s.")
        meta["fps"] = _fps(video.get("avg_frame_rate")) or _fps(video.get("r_frame_rate"))
    elif kind == "image":
        meta.update(duration=STILL_SECONDS, has_audio=False, fps=None)
    else:
        if audio is None:
            raise MediaError("No audio stream found in this file.")
        if not duration:
            raise MediaError("Could not determine the audio duration.")
    return meta


# ------------------------------------------------------------------ upload
def save_upload(pid: str, filename: str, stream: BinaryIO) -> dict:
    """Stream an upload to disk with a size cap, validate it, and register it as 'processing'."""
    name = Path(filename or "upload").name
    ext = Path(name).suffix.lower()
    kind = config.kind_for(ext)
    if kind is None:
        allowed = ", ".join(sorted(e.lstrip(".").upper() for e in config.ALLOWED_EXTS))
        raise MediaError(f"Unsupported file type '{ext or 'none'}'. Supported: {allowed}.")
    mid = uuid.uuid4().hex[:12]
    folder = config.project_dir(pid) / "media"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{mid}{ext}"
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise TooLarge(f"{name} exceeds the {config.MAX_UPLOAD_MB} MB upload limit.")
                out.write(chunk)
        if size == 0:
            raise MediaError(f"{name} is empty.")
        meta = describe(dest, kind)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    pos = (db.one("SELECT MAX(position) AS p FROM media WHERE project_id=?", (pid,)) or {}).get("p")
    info = {"url": url_for(dest), "videoCodec": meta["videoCodec"], "audioCodec": meta["audioCodec"],
            "bitrate": meta["bitrate"]}
    db.execute(
        """INSERT INTO media (id, project_id, name, kind, ext, size, path, status, error, position, duration,
           width, height, fps, has_audio, info, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (mid, pid, name, kind, ext.lstrip("."), size, rel(dest), "processing", None,
         (pos if pos is not None else -1) + 1, meta["duration"], meta["width"], meta["height"], meta["fps"],
         int(meta["has_audio"]), db.dumps(info), time.time()))
    return get(mid)


# ------------------------------------------------------------------ derived assets
def _even_scale(short_edge: int) -> str:
    return (f"scale='if(gte(iw,ih),-2,{short_edge})':'if(gte(iw,ih),{short_edge},-2)'")


def _peaks(path: Path, cache: Path, mid: str) -> tuple[Path, list[float]]:
    raw = analysis.audio_energy(path, PEAK_STEP)
    top = max(raw) if raw else 0.0
    peaks = [round(min(1.0, (r / top) ** 0.6), 3) for r in raw] if top > 0 else []
    out = cache / f"{mid}_peaks.json"
    out.write_text(json.dumps(peaks))
    return out, peaks


def process(mid: str, progress=lambda f, m: None) -> dict:
    """Generate thumbnails, preview proxy, filmstrip sprite and waveform for one media item."""
    m = get_row(mid)
    if m is None:
        raise MediaError("Media was removed before processing finished.")
    src = absolute(m["path"])
    cache = config.project_dir(m["project_id"]) / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    info = db.loads(m["info"], {})
    kind, dur = m["kind"], float(m["duration"] or 0)

    if kind == "audio":
        progress(0.2, "Reading waveform")
        peaks_file, _ = _peaks(src, cache, mid)
        info.update(peaksUrl=url_for(peaks_file), peakStep=PEAK_STEP)
    else:
        source = src
        if kind == "image":
            progress(0.1, "Creating still clip")
            still = cache / f"{mid}_still.mp4"
            _run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", "30", "-i", str(src), "-t", str(STILL_SECONDS),
                  "-vf", "scale='trunc(min(2160,iw)/2)*2':-2,format=yuv420p",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-tune", "stillimage", "-movflags", "+faststart",
                  str(still)], f"creating a still clip from {m['name']}")
            info["_renderPath"] = rel(still)
            source = still
        progress(0.25, "Creating thumbnail")
        thumb = cache / f"{mid}_thumb.jpg"
        at = min(max(0.0, dur * 0.1), max(0.0, dur - 0.1)) if kind == "video" else 0
        _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(source), "-frames:v", "1",
              "-vf", f"scale={THUMB_W}:-2", "-q:v", "4", str(thumb)], f"creating a thumbnail for {m['name']}")
        info["thumbUrl"] = url_for(thumb)

        progress(0.4, "Building preview proxy")
        proxy = cache / f"{mid}_proxy.mp4"
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-vf", f"{_even_scale(PROXY_SHORT_EDGE)},fps=30",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-g", "15", "-pix_fmt", "yuv420p"]
        cmd += ["-c:a", "aac", "-b:a", "96k", "-ac", "2"] if m["has_audio"] else ["-an"]
        _run(cmd + ["-movflags", "+faststart", str(proxy)], f"building a preview proxy for {m['name']}")
        info.update(proxyUrl=url_for(proxy), _proxyPath=rel(proxy))

        progress(0.75, "Building filmstrip")
        step = max(0.5, round(dur / 60, 2))
        count = max(1, int(math.ceil(dur / step)))
        w, h = int(m["width"] or 16), int(m["height"] or 9)
        tile_w = max(2, int(round(SPRITE_H * w / max(1, h) / 2)) * 2)
        sprite = cache / f"{mid}_sprite.jpg"
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(proxy), "-an", "-vf",
              f"fps=1/{step},scale={tile_w}:{SPRITE_H},tile={count}x1", "-frames:v", "1", "-q:v", "6", str(sprite)],
             f"building a filmstrip for {m['name']}")
        info.update(spriteUrl=url_for(sprite), sprite={"step": step, "count": count, "tileW": tile_w, "tileH": SPRITE_H})

        if m["has_audio"]:
            progress(0.9, "Reading waveform")
            peaks_file, _ = _peaks(proxy, cache, mid)
            info.update(peaksUrl=url_for(peaks_file), peakStep=PEAK_STEP)

    if get_row(mid) is None:  # removed while processing: clean up what we just made
        remove_files(m, info)
        raise MediaError("Media was removed while processing.")
    db.execute("UPDATE media SET status='ready', error=NULL, info=? WHERE id=?", (db.dumps(info), mid))
    return get(mid)


def mark_processing(mid: str) -> None:
    db.execute("UPDATE media SET status='processing', error=NULL WHERE id=?", (mid,))


def mark_failed(mid: str, error: str) -> None:
    db.execute("UPDATE media SET status='error', error=? WHERE id=?", (error[:500], mid))


def remove_files(m: dict, info: dict | None = None) -> None:
    info = info if info is not None else db.loads(m["info"], {})
    absolute(m["path"]).unlink(missing_ok=True)
    cache = config.project_dir(m["project_id"]) / "cache"
    for f in cache.glob(f"{m['id']}_*"):
        if f.is_dir():
            shutil.rmtree(f, ignore_errors=True)
        else:
            f.unlink(missing_ok=True)


def delete(mid: str) -> None:
    m = get_row(mid)
    if m is None:
        return
    db.execute("DELETE FROM media WHERE id=?", (mid,))
    remove_files(m)


def reorder(pid: str, ids: list[str]) -> list[dict]:
    existing = {r["id"] for r in db.query("SELECT id FROM media WHERE project_id=?", (pid,))}
    if set(ids) != existing:
        raise MediaError("Reorder list must contain exactly the project's media ids.")
    for i, mid in enumerate(ids):
        db.execute("UPDATE media SET position=? WHERE id=?", (i, mid))
    return list_media(pid)


def pending_ids() -> list[str]:
    """Media left 'processing' (e.g. by a server restart) so it can be queued again."""
    return [r["id"] for r in db.query("SELECT id FROM media WHERE status='processing'")]

