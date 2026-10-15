"""Deterministic test media for the FrameFlow backend tests (generated with FFmpeg, no downloads).

multiscene.mp4  24 s 1280x720: four visually distinct 6 s shots (hard cuts) with moving content and a
                tone that pauses inside each shot, so scene detection, silence removal and scoring all
                have real signal to work with.
portrait.mov    6 s 720x1280, no audio track.
still.png       1600x900 picture.
music.wav       30 s, 120 BPM click track over a soft pad (beat period 0.5 s).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

SHOTS = [
    "testsrc2=size=1280x720:rate=30",
    "mandelbrot=size=1280x720:rate=30:start_scale=3:end_scale=0.002",
    "life=size=1280x720:rate=30:mold=10:ratio=0.2:death_color=#203040:life_color=#ffcc00",
    "cellauto=size=1280x720:rate=30:rule=110,negate",
]
GAPS = [(2.0, 3.2), (8.4, 9.6), (14.0, 15.4), (20.2, 21.0)]


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])


def make(folder: Path) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    out = {k: folder / v for k, v in {"multiscene": "multiscene.mp4", "portrait": "portrait.mov",
                                      "still": "still.png", "music": "music.wav"}.items()}
    if not out["multiscene"].exists():
        inputs, labels = [], []
        for i, src in enumerate(SHOTS):
            inputs += ["-f", "lavfi", "-t", "6", "-i", src]
            labels.append(f"[{i}:v]format=yuv420p,setsar=1[v{i}]")
        gate = "+".join(f"between(t,{a},{b})" for a, b in GAPS)
        inputs += ["-f", "lavfi", "-i", f"sine=frequency=220:duration=24,volume='if({gate},0,0.5)':eval=frame"]
        graph = ";".join(labels) + ";" + "".join(f"[v{i}]" for i in range(len(SHOTS))) + \
            f"concat=n={len(SHOTS)}:v=1:a=0[v]"
        _run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph, "-map", "[v]", "-map", "4:a",
              "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
              str(out["multiscene"])])
    if not out["portrait"].exists():
        _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=720x1280:rate=30:duration=6",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out["portrait"])])
    if not out["still"].exists():
        _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "smptehdbars=size=1600x900", "-frames:v", "1",
              str(out["still"])])
    if not out["music"].exists():
        click = "0.8*exp(-60*mod(t,0.5))*sin(2*PI*1000*t)"
        pad = "0.1*sin(2*PI*110*t)"
        _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
              f"aevalsrc='{click}+{pad}':s=44100:d=30", str(out["music"])])
    return out
