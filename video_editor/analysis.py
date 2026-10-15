"""Media analysis helpers: silence detection, activity scoring, SRT parsing."""
from __future__ import annotations

import re
from pathlib import Path

from .ffmpeg_ops import FFmpegError, run_process


def detect_silences(path: Path, noise_db: float = -30.0, min_silence: float = 0.5) -> list[tuple[float, float]]:
    """Return (start, end) silent intervals reported by ffmpeg silencedetect."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
           "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"]
    res = run_process(cmd)
    if res.returncode != 0:
        raise FFmpegError(f"silencedetect failed for {path.name}:\n{res.stderr[-500:]}")
    starts = [float(m) for m in re.findall(r"silence_start: (-?[\d.]+)", res.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end: (-?[\d.]+)", res.stderr)]
    out = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else float("inf")  # silence runs to end of file
        out.append((max(0.0, s), e))
    return out


def audio_energy(path: Path, step: float = 0.5) -> list[float]:
    """Mean RMS per `step` seconds (decoded to 8 kHz mono). Empty if no audio."""
    import numpy as np

    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "8000",
           "-f", "s16le", "-"]
    res = run_process(cmd, text=False)
    if res.returncode != 0 or not res.stdout:
        return []
    samples = np.frombuffer(res.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(8000 * step)
    if len(samples) < n:
        return [float(np.sqrt(np.mean(samples ** 2)))] if len(samples) else []
    frames = len(samples) // n
    chunks = samples[: frames * n].reshape(frames, n)
    return [float(x) for x in np.sqrt((chunks ** 2).mean(axis=1))]


def visual_activity(path: Path, step: float = 0.5) -> list[float]:
    """Mean scene-change score per `step` seconds (ffmpeg scene detector)."""
    fps = 1.0 / step
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-an",
           "-vf", f"fps={fps},scale=160:-2,select=gte(scene\\,0),metadata=mode=print:file=-",
           "-f", "null", "-"]
    res = run_process(cmd)
    if res.returncode != 0:
        return []
    scores = [float(m) for m in re.findall(r"lavfi\.scene_score=([\d.]+)", res.stdout)]
    return scores


_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def _ts(s: str) -> float:
    m = _TS.search(s)
    if not m:
        raise ValueError(f"bad timestamp: {s!r}")
    h, mi, se, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(se) + int(ms.ljust(3, "0")[:3]) / 1000.0


def parse_srt(text: str) -> list[dict]:
    """Parse SRT/VTT text into [{start, end, text}] (seconds)."""
    cues = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
    for block in blocks:
        lines = [l for l in block.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if "-->" in line:
                a, b = line.split("-->")[:2]
                body = " ".join(l.strip() for l in lines[i + 1:])
                body = re.sub(r"<[^>]+>", "", body).strip()
                if body:
                    cues.append({"start": _ts(a), "end": _ts(b.strip().split()[0]), "text": body})
                break
    return cues
