"""EDL -> validated engine plan -> FFmpeg render (video_editor.engine)."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from video_editor import engine
from video_editor.ffmpeg_ops import probe_video

from . import layout as lay
from . import media as media_svc
from .editing import crop_offset

# Export quality presets: target video bitrate (kbps) per short edge, encoder preset, audio bitrate.
QUALITY = {
    "draft": {720: 2500, 1080: 4500, "preset": "veryfast", "audio": "128k"},
    "standard": {720: 5000, 1080: 8000, "preset": "fast", "audio": "160k"},
    "high": {720: 8000, 1080: 12000, "preset": "medium", "audio": "192k"},
}
PREVIEW = {"crf": 23, "preset": "veryfast", "audio_bitrate": "128k", "fps": 30}


class RenderError(RuntimeError):
    pass


def video_kbps(quality: str, short_edge: int, fps: int) -> int:
    base = QUALITY[quality][short_edge]
    return int(base * 1.5) if fps > 30 else base


def estimate_bytes(duration: float, quality: str, short_edge: int, fps: int) -> int:
    audio = int(QUALITY[quality]["audio"].rstrip("k"))
    return int((video_kbps(quality, short_edge, fps) + audio) * 1000 / 8 * duration * 1.01)


def safe_filename(name: str) -> str:
    stem = re.sub(r"[^\w\- .()]+", "", Path(name).stem).strip(" .") or "frameflow-export"
    return stem[:100]


def edl_to_plan(edl: dict, export: dict) -> tuple[dict, dict]:
    """Return (engine plan, layout). Raises RenderError with an actionable message."""
    clips = edl.get("clips") or []
    if not clips:
        raise RenderError("The timeline is empty. Generate an edit or add clips first.")
    order: list[str] = []
    for c in clips:
        if c["mediaId"] not in order:
            order.append(c["mediaId"])
    try:
        sources = [{"path": str(media_svc.render_path(mid))} for mid in order]
    except media_svc.MediaError as e:
        raise RenderError(f"{e} Remove its clips from the timeline or re-upload the file.")
    index = {mid: i for i, mid in enumerate(order)}
    for c in clips:
        m = media_svc.get_row(c["mediaId"])
        if c["srcEnd"] > float(m["duration"] or 0) + 0.05:
            raise RenderError(f"Clip '{c.get('label') or m['name']}' ends after its source media ({m['duration']:.2f}s).")
    lt = lay.layout(clips, edl.get("transition"))
    aspect = edl.get("aspect", "16:9")
    segments = []
    for c in clips:
        m = media_svc.get_row(c["mediaId"])
        focus = crop_offset((c.get("focusX", 0.5), c.get("focusY", 0.5)), float(m["width"] or 16),
                            float(m["height"] or 9), aspect)
        segments.append({"clip": index[c["mediaId"]], "start": c["srcStart"], "end": c["srcEnd"],
                         "break": bool(c.get("sceneBreak")), "focus": list(focus)})
    skills: list[dict] = []
    if lt["transition"] > 0:
        skills.append({"id": "transition.crossfade",
                       "settings": {"type": edl["transition"]["type"], "duration": lt["transition"]}})
    if edl.get("look") and edl["look"] != "none":
        skills.append({"id": "color.look", "settings": {"look": edl["look"]}})
    audio = edl.get("audio") or {}
    if audio.get("clean"):
        skills.append({"id": "audio.clean", "settings": {}})
    if edl.get("music"):
        mus = edl["music"]
        try:
            path = media_svc.render_path(mus["mediaId"])
        except media_svc.MediaError as e:
            raise RenderError(f"Background music: {e}")
        skills.append({"id": "audio.music_bed", "settings": {"path": str(path), "volume": mus["volume"],
                                                             "duck": bool(mus.get("duck"))}})
    if audio.get("fades"):
        skills.append({"id": "audio.fades", "settings": {"fade_in": 0.5, "fade_out": 1.2}})
    if audio.get("normalize"):
        skills.append({"id": "audio.loudnorm", "settings": {"target_lufs": audio.get("lufs", -14)}})
    if edl.get("burnCaptions") and edl.get("captions"):
        spans = lay.caption_spans(edl["captions"], clips, lt["clips"])
        if spans:
            cues = [{"clip": index[c["mediaId"]], "start": c["srcStart"], "end": c["srcEnd"], "text": c["text"]}
                    for c in edl["captions"] if c["mediaId"] in index and c["text"].strip()]
            skills.append({"id": "captions.burn", "settings": {"cues": cues, "font_scale": 0.05, "box": True}})
    for t in edl.get("titles") or []:
        if t["text"].strip() and t["start"] < lt["duration"]:
            skills.append({"id": "graphics.title", "settings": {"text": t["text"], "start": t["start"],
                                                                "duration": t["duration"], "position": t["position"]}})
    plan = {"version": 1, "goal": f"FrameFlow {edl.get('style')} edit", "mode": "custom", "sources": sources,
            "segments": segments, "skills": skills,
            "export": {"aspect": edl.get("aspect", "16:9"), "fit": edl.get("fit", "crop"), **export},
            "rationale": list(edl.get("notes") or [])}
    return plan, lt


def render(edl: dict, export: dict, out_path: Path, progress: Callable[[float, str], None]) -> dict:
    """Render `edl` to `out_path`; verify the output's size and duration against the plan."""
    plan, lt = edl_to_plan(edl, export)
    work = Path(tempfile.mkdtemp(prefix="ff_render_"))
    try:
        res = engine.execute_plan(plan, progress, out_dir=work)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(res.output), out_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    info = probe_video(out_path)
    w, h = engine.resolve_resolution({"aspect": edl.get("aspect", "16:9"), "short_edge": export["short_edge"]}, [])
    if (info.width, info.height) != (w, h):
        raise RenderError(f"Rendered {info.width}x{info.height}, expected {w}x{h}.")
    warnings = list(res.warnings)
    if abs(info.duration - lt["duration"]) > 0.3:
        warnings.append(f"Output is {info.duration:.2f}s; the timeline is {lt['duration']:.2f}s.")
    return {"path": out_path, "duration": round(info.duration, 3), "width": info.width, "height": info.height,
            "fps": info.fps, "size": out_path.stat().st_size, "warnings": warnings, "notes": res.plan["rationale"],
            "timeline": res.timeline}


def preview_export(resolution: int) -> dict:
    return {"short_edge": resolution, "fps": PREVIEW["fps"], "crf": PREVIEW["crf"], "preset": PREVIEW["preset"],
            "audio_bitrate": PREVIEW["audio_bitrate"]}


def final_export(settings: dict) -> dict:
    q = QUALITY[settings["quality"]]
    return {"short_edge": settings["resolution"], "fps": settings["fps"], "crf": 20, "preset": q["preset"],
            "audio_bitrate": q["audio"],
            "video_bitrate_kbps": video_kbps(settings["quality"], settings["resolution"], settings["fps"])}


def write_sidecar(out_path: Path, edl: dict, export: dict) -> Path:
    side = out_path.with_suffix(".frameflow.json")
    side.write_text(json.dumps({"edl": edl, "export": export}, indent=2))
    return side
