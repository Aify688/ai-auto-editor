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
from . import matting, music_library
from .editing import crop_offset

# Export quality presets: target video bitrate (kbps) per short edge, encoder preset, audio bitrate.
QUALITY = {
    "draft": {720: 2500, 1080: 4500, 2160: 18000, "preset": "veryfast", "audio": "128k"},
    "standard": {720: 5000, 1080: 8000, 2160: 35000, "preset": "fast", "audio": "160k"},
    "high": {720: 8000, 1080: 12000, 2160: 50000, "preset": "medium", "audio": "192k"},
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


def _bg_for_clip(c: dict, m: dict) -> dict | None:
    """Render-time description of a clip's AI background removal, or None when it is off."""
    cfg = c.get("bgRemoval") or {}
    if not cfg.get("enabled"):
        return None
    if not matting.has_matte(m):
        raise RenderError(f"'{m['name']}' has not been analysed for AI Background Removal yet. "
                          "Run the effect on the clip first.")
    out = {"matte": str(matting.matte_path(m)), "mode": cfg.get("mode", "color"), "color": cfg.get("color", "#00B140"),
           "blur_sigma": matting.blur_sigma(float(cfg.get("blur", 50)), int(m["width"] or 1920))}
    if out["mode"] in ("image", "video"):
        bid = cfg.get("bgMediaId")
        row = media_svc.get_row(bid) if bid else None
        if row is None or row["status"] != "ready":
            raise RenderError("Choose an uploaded image or video to use as the new background.")
        if out["mode"] == "image" and row["kind"] != "image":
            raise RenderError(f"'{row['name']}' is not an image. Pick an image or switch the background type.")
        if out["mode"] == "video" and row["kind"] != "video":
            raise RenderError(f"'{row['name']}' is not a video. Pick a video or switch the background type.")
        out["bg_path"] = str(media_svc.render_path(bid))
    return out


def ensure_mattes(edl: dict, progress: Callable[[float, str], None]) -> bool:
    """Analyse (once, cached) every source that has background removal switched on. True if any work ran."""
    todo: dict[str, dict] = {}
    for c in edl.get("clips") or []:
        if (c.get("bgRemoval") or {}).get("enabled") and not c.get("rejected") and not c.get("boring"):
            m = media_svc.get_row(c["mediaId"])
            if m is not None and not matting.has_matte(m):
                todo[m["id"]] = m
    for i, m in enumerate(todo.values()):
        try:
            matting.compute_matte(m, lambda f, msg, i=i: progress((i + f) / len(todo) * 0.35, msg))
        except matting.MattingError as e:
            raise RenderError(str(e))
    return bool(todo)


def edl_to_plan(edl: dict, export: dict) -> tuple[dict, dict]:
    """Return (engine plan, layout). Raises RenderError with an actionable message."""
    clips = [c for c in (edl.get("clips") or [])
             if not c.get("rejected", False) and not c.get("boring", False)]
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
        seg = {"clip": index[c["mediaId"]], "start": c["srcStart"], "end": c["srcEnd"],
               "break": bool(c.get("sceneBreak")), "focus": list(focus)}
        if abs(float(c.get("volume", 1.0)) - 1.0) > 1e-6:
            seg["volume"] = float(c["volume"])
        if c.get("audioEffect") and c["audioEffect"] != "none":
            seg["audio_effect"] = c["audioEffect"]
        if c.get("effects"):
            seg["effects"] = c["effects"]
        if c.get("filter"):
            seg["filter"] = c["filter"]
        if c.get("transitionType"):
            seg["transition_type"] = c["transitionType"]
        kfs = c.get("keyframes") or []
        if kfs:
            seg["keyframes"] = kfs
        if c.get("freeze"):
            seg["freeze"] = c["freeze"]
        elif abs(float(c.get("speed") or 1.0) - 1.0) > 1e-6:
            seg["rate"] = float(c["speed"])
        bg = _bg_for_clip(c, m)
        if bg:
            seg["bg"] = bg
        segments.append(seg)
    skills: list[dict] = []
    if lt["transition"] > 0:
        skills.append({"id": "transition.crossfade",
                       "settings": {"type": edl["transition"]["type"], "duration": lt["transition"]}})
    if edl.get("look") and edl["look"] != "none":
        skills.append({"id": "color.look", "settings": {"look": edl["look"]}})
    audio = edl.get("audio") or {}
    if audio.get("clean"):
        skills.append({"id": "audio.clean", "settings": {}})
    clips_a = edl.get("audioClips") or ([{"id": "legacy", "mediaId": edl["music"]["mediaId"], "kind": "music", "start": 0.0,
                                         "trimIn": 0.0, "duration": None, "volume": edl["music"]["volume"], "fadeIn": 0.0,
                                         "fadeOut": 0.0, "loop": True, "duck": bool(edl["music"].get("duck"))}]
                                        if edl.get("music") else [])
    tracks = []
    for ac in clips_a:
        try:
            if music_library.is_library_id(ac["mediaId"]):
                path, src_len = music_library.resolve_path(ac["mediaId"]), float(music_library.by_mood(ac["mediaId"][4:])["duration"])
            else:
                path = media_svc.render_path(ac["mediaId"])
                row = media_svc.get_row(ac["mediaId"])
                src_len = float((row or {}).get("duration") or 0)
        except (media_svc.MediaError, KeyError, FileNotFoundError, TypeError) as e:
            raise RenderError(f"Audio clip: {e}")
        trim = float(ac.get("trimIn") or 0.0)
        if src_len and trim >= src_len - 0.05:
            raise RenderError(f"An audio clip starts at {trim:.1f}s but its file is only {src_len:.1f}s long. Trim it again.")
        length = ac.get("duration")
        if length is not None and not ac.get("loop") and src_len:
            length = min(float(length), src_len - trim)         # without looping the clip cannot outlast its source
        elif length is None and not ac.get("loop") and src_len:
            length = src_len - trim
        tracks.append({"path": str(path), "volume": ac.get("volume", 0.35), "duck": bool(ac.get("duck", True)),
                       "start": float(ac.get("start") or 0.0), "trim_in": trim, "length": length,
                       "fade_in": float(ac.get("fadeIn") or 0.0), "fade_out": float(ac.get("fadeOut") or 0.0),
                       "loop": bool(ac.get("loop")), "effect": ac.get("effect") or "none"})
    if tracks:
        skills.append({"id": "audio.tracks", "settings": {"tracks": tracks}})
    if audio.get("fades"):
        skills.append({"id": "audio.fades", "settings": {"fade_in": 0.5, "fade_out": 1.2}})
    if audio.get("normalize"):
        skills.append({"id": "audio.loudnorm", "settings": {"target_lufs": audio.get("lufs", -14)}})
    if edl.get("burnCaptions") and edl.get("captions"):
        spans = lay.caption_spans(edl["captions"], clips, lt["clips"])
        if spans:
            cs = edl.get("captionStyle") or {}
            font_map = {"small": 0.035, "medium": 0.05, "large": 0.07}
            font_scale = font_map.get(cs.get("fontSize", "medium"), 0.05)
            bg = cs.get("background", "box")
            cues = []
            for c in edl["captions"]:
                if c["mediaId"] not in index or not c["text"].strip():
                    continue
                cue = {"clip": index[c["mediaId"]], "start": c["srcStart"], "end": c["srcEnd"], "text": c["text"]}
                if c.get("words"):
                    cue["words"] = [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in c["words"]]
                cues.append(cue)
            skills.append({"id": "captions.burn", "settings": {
                "cues": cues, "font_scale": font_scale, "box": bg == "box",
                "position": cs.get("position", "bottom"),
                "color": cs.get("color", "#FFFFFF"),
                "highlight_color": cs.get("highlightColor", "#FFD700"),
                "outline_color": cs.get("outlineColor", "#000000"),
                "background": bg, "uppercase": bool(cs.get("uppercase")),
                "karaoke": bool(cs.get("karaoke")), "animation": cs.get("animation", "none"),
            }})
    for t in edl.get("titles") or []:
        if t["text"].strip() and t["start"] < lt["duration"]:
            keys = ("position", "x", "y", "size", "rotation", "font", "weight", "color", "opacity", "align", "strokeColor",
                    "strokeWidth", "shadow", "background", "backgroundOpacity", "animation")
            skills.append({"id": "graphics.title", "settings": {"text": t["text"], "start": t["start"],
                                                                "duration": t["duration"],
                                                                **{k: t[k] for k in keys if t.get(k) is not None}}})
    engine_aspect = "match_first" if aspect == "original" else aspect
    plan = {"version": 1, "goal": f"FrameFlow {edl.get('style')} edit", "mode": "custom", "sources": sources,
            "segments": segments, "skills": skills,
            "export": {"aspect": engine_aspect, "fit": edl.get("fit", "crop"), **export},
            "rationale": list(edl.get("notes") or [])}
    return plan, lt


def render(edl: dict, export: dict, out_path: Path, progress: Callable[[float, str], None]) -> dict:
    """Render `edl` to `out_path`; verify the output's size and duration against the plan."""
    base = 0.35 if ensure_mattes(edl, progress) else 0.0     # background-removal analysis is the first slice
    plan, lt = edl_to_plan(edl, export)
    work = Path(tempfile.mkdtemp(prefix="ff_render_"))
    try:
        res = engine.execute_plan(plan, lambda f, msg: progress(base + (1 - base) * f, msg), out_dir=work)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(res.output), out_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    info = probe_video(out_path)
    aspect = edl.get("aspect", "16:9")
    if aspect != "original":
        w, h = engine.resolve_resolution({"aspect": aspect, "short_edge": export["short_edge"]}, [])
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


def _ts(seconds: float, fmt: str) -> str:
    """Format seconds to SRT (HH:MM:SS,mmm) or VTT (HH:MM:SS.mmm) timestamp."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    sep = "." if fmt == "vtt" else ","
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def build_subtitle_text(edl: dict, fmt: str) -> str | None:
    """Render the EDL's captions as SRT/VTT text, timed against the active (non-rejected/boring)
    clips exactly like the burned-in captions. Returns None if there's nothing to export."""
    if not edl.get("captions"):
        return None
    clips = [c for c in edl["clips"] if not c.get("rejected") and not c.get("boring")]
    if not clips:
        return None
    lt = lay.layout(clips, edl.get("transition"))
    spans = lay.caption_spans(edl["captions"], clips, lt["clips"])
    if not spans:
        return None
    lines: list[str] = []
    if fmt == "vtt":
        lines.append("WEBVTT\n")
    for i, sp in enumerate(spans, 1):
        if fmt == "srt":
            lines.append(str(i))
        lines.append(f"{_ts(sp['outStart'], fmt)} --> {_ts(sp['outEnd'], fmt)}")
        lines.append(sp["text"])
        lines.append("")
    return "\n".join(lines)
