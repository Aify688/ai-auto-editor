"""Editing engine: executes a validated plan with FFmpeg.

Stages
  1. segment : trim each kept range, apply per-clip video/audio filters, resize, normalise
  2. join    : concat (hard cuts) or xfade/acrossfade between different clips
  3. final   : overlays (captions/graphics) + audio mastering + export encode
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
import uuid

from . import ffmpeg_ops, project, registry, validate
from .overlay import OverlayItem, build_overlay_track
from .skills import MasterCtx, MasterFrag, OverlayCtx, SegCtx, SegFrag

ProgressCallback = Callable[[float, str], None]
OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "outputs"
INTERMEDIATE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2"]


@dataclass
class RenderResult:
    output: Path
    duration: float
    timeline: list[dict]
    plan: dict
    plan_path: Path
    edl_path: Path
    warnings: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)


def _noop(f: float, m: str) -> None:
    pass


def _even(x: float) -> int:
    v = int(round(x))
    return v if v % 2 == 0 else v + 1


def resolve_resolution(export: dict, clips: list[ffmpeg_ops.ClipInfo]) -> tuple[int, int]:
    short = int(export["short_edge"])
    if export["aspect"] == "match_first":
        c = clips[0]
        scale = short / min(c.width, c.height)
        return _even(c.width * scale), _even(c.height * scale)
    a, b = validate.ASPECTS[export["aspect"]]
    if a >= b:
        return _even(short * a / b), _even(short)
    return _even(short), _even(short * b / a)


# ------------------------------------------------------------------ stage 1
def resize_graph(src: str, dst: str, w: int, h: int, fit: str, fps: int,
                 focus: tuple[float, float] = (0.5, 0.5)) -> str:
    tail = f"fps={fps},format=yuv420p,setsar=1"
    if fit == "blur":
        return (f"[{src}]split[bg0][fg0];"
                f"[bg0]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=24:3[bg];"
                f"[fg0]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{tail}[{dst}]")
    if fit == "pad":
        return (f"[{src}]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,{tail}[{dst}]")
    fx, fy = (min(1.0, max(0.0, float(v))) for v in focus)
    crop = f"crop={w}:{h}" if (fx, fy) == (0.5, 0.5) else f"crop={w}:{h}:(iw-{w})*{fx:.3f}:(ih-{h})*{fy:.3f}"
    return f"[{src}]scale={w}:{h}:force_original_aspect_ratio=increase,{crop},{tail}[{dst}]"


def render_segment(clip: ffmpeg_ops.ClipInfo, start: float, end: float, out: Path, w: int, h: int,
                   fit: str, fps: int, frag: SegFrag, focus: tuple[float, float] = (0.5, 0.5)) -> float:
    """Render one kept range; returns its output duration (after speed)."""
    src_dur = end - start
    out_dur = src_dur / frag.speed
    pre = ",".join(frag.vf) if frag.vf else "null"
    graph = f"[0:v]{pre}[pre];" + resize_graph("pre", "v", w, h, fit, fps, focus)
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{src_dur:.3f}", "-i", str(clip.path)]
    if clip.has_audio:
        af = ",".join(frag.af + ["aresample=44100", "aformat=channel_layouts=stereo"])
        graph += f";[0:a]{af}[a]"
        amap = "[a]"
    else:
        cmd += ["-f", "lavfi", "-t", f"{out_dur:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        amap = "1:a:0"
    cmd += ["-filter_complex", graph, "-map", "[v]", "-map", amap, "-t", f"{out_dur:.3f}", *INTERMEDIATE, str(out)]
    ffmpeg_ops._run(cmd, f"rendering segment {start:.2f}-{end:.2f}s of {clip.path.name}")
    return out_dur


# ------------------------------------------------------------------ stage 2
def build_join(files: list[Path], transition: dict | None, out: Path, fps: int | None = None) -> list[float]:
    """Join scene files. Returns each file's start offset on the output timeline."""
    if len(files) == 1:
        shutil.copy(files[0], out)
        return [0.0]
    if not transition:
        ffmpeg_ops.concat_segments(files, out)
        offs, t = [], 0.0
        for f in files:
            offs.append(t)
            t += ffmpeg_ops.probe_video(f).duration
        return offs
    d = float(transition["duration"])
    durs = [ffmpeg_ops.probe_video(f).duration for f in files]
    aparts, offs = [], [0.0]
    # xfade needs identical frame rates/timebases; stream-copied scene files can drift (e.g. 359/12).
    rate = fps or round(ffmpeg_ops.probe_video(files[0]).fps) or 30
    vparts = [f"[{i}:v]fps={rate},settb=AVTB[n{i}]" for i in range(len(files))]
    vprev, aprev = "n0", "0:a"
    acc = durs[0]
    for i in range(1, len(files)):
        offset = acc - d
        offs.append(offset)
        vlab, alab = f"v{i}", f"a{i}"
        vparts.append(f"[{vprev}][n{i}]xfade=transition={transition['type']}:duration={d}:offset={offset:.3f}[{vlab}]")
        aparts.append(f"[{aprev}][{i}:a]acrossfade=d={d}[{alab}]")
        vprev, aprev = vlab, alab
        acc = offset + durs[i]
    cmd = ["ffmpeg", "-y"]
    for f in files:
        cmd += ["-i", str(f)]
    cmd += ["-filter_complex", ";".join(vparts + aparts), "-map", f"[{vprev}]", "-map", f"[{aprev}]",
            *INTERMEDIATE, str(out)]
    ffmpeg_ops._run(cmd, "joining clips with transitions")
    return offs


# ------------------------------------------------------------------ stage 3
def _rate_args(export: dict) -> list[str]:
    """Constant quality (CRF) by default; a target bitrate when given, so file size is predictable."""
    kbps = export.get("video_bitrate_kbps")
    if kbps:
        k = int(kbps)
        return ["-b:v", f"{k}k", "-maxrate", f"{int(k * 1.5)}k", "-bufsize", f"{k * 2}k"]
    return ["-crf", str(export["crf"])]


def encode_final(joined: Path, out: Path, export: dict, duration: float, w: int, h: int,
                 overlay_list: Path | None, master: MasterFrag, has_audio: bool = True) -> None:
    cmd = ["ffmpeg", "-y", "-i", str(joined)]
    n = 1
    ov_idx = mus_idx = None
    if overlay_list is not None:
        cmd += ["-f", "concat", "-safe", "0", "-i", str(overlay_list)]
        ov_idx, n = n, n + 1
    if master.music:
        cmd += ["-stream_loop", "-1", "-i", str(master.music["path"])]
        mus_idx, n = n, n + 1

    g = []
    if ov_idx is not None:
        g.append(f"[{ov_idx}:v]format=rgba[ov];[0:v][ov]overlay=0:0:eof_action=pass[v]")
        vmap = "[v]"
    else:
        vmap = "0:v"

    voice = ",".join(master.voice_af) or "anull"
    g.append(f"[0:a]{voice}[va]")
    cur = "va"
    if master.music:
        m = master.music
        g.append(f"[{mus_idx}:a]volume={m['volume']},aformat=channel_layouts=stereo,"
                 f"atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[mus]")
        if m["duck"]:
            g.append("[va]asplit=2[vs][vm];"
                     "[mus][vs]sidechaincompress=threshold=0.03:ratio=10:attack=20:release=400[md];"
                     "[vm][md]amix=inputs=2:duration=first:normalize=0[mix]")
        else:
            g.append("[va][mus]amix=inputs=2:duration=first:normalize=0[mix]")
        cur = "mix"
    final = ",".join(master.final_af) or "anull"
    g.append(f"[{cur}]{final}[a]")

    cmd += ["-filter_complex", ";".join(g), "-map", vmap, "-map", "[a]", "-t", f"{duration:.3f}",
            "-r", str(export["fps"]), "-c:v", "libx264", "-preset", export["preset"], *_rate_args(export),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", export["audio_bitrate"], "-ar", "44100",
            "-movflags", "+faststart", str(out)]
    ffmpeg_ops._run(cmd, "final encode")


# ------------------------------------------------------------------ driver
def execute_plan(plan: dict, progress_cb: ProgressCallback = _noop, out_dir: Path | None = None) -> RenderResult:
    ffmpeg_ops.check_binaries()
    v = validate.require_valid(plan)          # raises PlanError; nothing renders on invalid plans
    plan, clips = v.plan, v.clips
    exp = plan["export"]
    skills = {e["id"]: e["settings"] for e in plan["skills"]}
    w, h = resolve_resolution(exp, clips)
    fps = int(exp["fps"])
    out_dir = out_dir or OUTPUTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # gather per-segment filter fragments through each handler
    seg_ctx = SegCtx(w, h, fps)
    frag = SegFrag()
    for sid, st in skills.items():
        cap = registry.get(sid)
        if cap.stage == "segment" and sid != "cut.trim":
            f = cap.resolve_handler()(st, seg_ctx)
            frag.vf += f.vf
            frag.af += f.af
            frag.speed *= f.speed

    work = Path(tempfile.mkdtemp(prefix="ave_engine_"))
    try:
        segs = plan["segments"]
        seg_files, seg_durs = [], []
        for i, s in enumerate(segs):
            progress_cb(0.05 + 0.55 * i / len(segs), f"Rendering segment {i + 1}/{len(segs)}")
            f = work / f"seg_{i:03d}.mp4"
            focus = tuple(s.get("focus") or (0.5, 0.5))
            seg_durs.append(render_segment(clips[s["clip"]], s["start"], s["end"], f, w, h, exp["fit"], fps, frag,
                                           focus))
            seg_files.append(f)

        # group consecutive segments from the same clip into scenes
        groups: list[list[int]] = []
        for i, s in enumerate(segs):
            if groups and segs[groups[-1][-1]]["clip"] == s["clip"] and not s.get("break"):
                groups[-1].append(i)
            else:
                groups.append([i])
        trans = skills.get("transition.crossfade") if len(groups) > 1 else None
        scene_files = []
        for gi, idxs in enumerate(groups):
            if len(idxs) == 1:
                scene_files.append(seg_files[idxs[0]])
            else:
                sf = work / f"scene_{gi:03d}.mp4"
                ffmpeg_ops.concat_segments([seg_files[i] for i in idxs], sf)
                scene_files.append(sf)

        progress_cb(0.65, "Joining clips")
        joined = work / "joined.mp4"
        if trans:
            cap = registry.get("transition.crossfade")
            scene_offsets = cap.resolve_handler()(scene_files, trans, joined, fps)
        else:
            scene_offsets = build_join(scene_files, None, joined)

        timeline, seg_starts = [], []
        for gi, idxs in enumerate(groups):
            t = scene_offsets[gi]
            for i in idxs:
                s = segs[i]
                timeline.append({"clip": s["clip"], "start": s["start"], "end": s["end"],
                                 "out_start": round(t, 3), "out_end": round(t + seg_durs[i], 3)})
                seg_starts.append((s["clip"], s["start"], s["end"], t))
                t += seg_durs[i]
        duration = ffmpeg_ops.probe_video(joined).duration

        progress_cb(0.75, "Captions, graphics and audio master")
        o_ctx = OverlayCtx((w, h), duration, seg_starts, frag.speed)
        items: list[OverlayItem] = []
        for e in plan["skills"]:
            cap = registry.get(e["id"])
            if cap.stage == "overlay":
                items += cap.resolve_handler()(e["settings"], o_ctx)
        overlay_list = build_overlay_track(items, (w, h), duration, work) if items else None

        master = MasterFrag()
        m_ctx = MasterCtx(duration)
        for e in plan["skills"]:
            cap = registry.get(e["id"])
            if cap.stage == "master":
                mf = cap.resolve_handler()(e["settings"], m_ctx)
                master.voice_af += mf.voice_af
                master.final_af += mf.final_af
                master.music = mf.music or master.music

        out = out_dir / f"edited_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.mp4"
        encode_final(joined, out, exp, duration, w, h, overlay_list, master)

        plan_path = project.save_plan({**plan, "_timeline": timeline}, out.with_suffix(".plan.json"))
        edl_path = project.export_edl(timeline, [s["path"] for s in plan["sources"]], fps, out.with_suffix(".edl"))
        progress_cb(1.0, "Done")
        return RenderResult(out, duration, timeline, plan, plan_path, edl_path, v.warnings,
                            validate.review_plan(plan, clips))
    finally:
        shutil.rmtree(work, ignore_errors=True)
