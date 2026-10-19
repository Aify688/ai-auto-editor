"""Media analysis with on-disk caching.

Rule-based / signal-processing analysis (no generative AI):
  scenes     PySceneDetect ContentDetector on the preview proxy
  features   OpenCV: sharpness (Laplacian variance), motion (frame difference), brightness,
             Haar-cascade faces, motion centroid
  audio      FFmpeg silencedetect + RMS energy
  speech     faster-whisper transcription (local model), only when captions are requested
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Callable

from video_editor import analysis as va
from video_editor.ffmpeg_ops import FFmpegError, run_streaming

from .. import config, db
from . import media as media_svc

ANALYSIS_VERSION = 2
SILENCE_DB = -35.0
SILENCE_MIN = 0.45
Progress = Callable[[float], None]


class AnalysisError(RuntimeError):
    pass


def _cache_file(m: dict, name: str) -> Path:
    return config.project_dir(m["project_id"]) / "cache" / f"{m['id']}_{name}.json"


def _cached(m: dict, name: str, build: Callable[[], dict]) -> dict:
    f = _cache_file(m, name)
    if f.exists():
        try:
            data = json.loads(f.read_text())
            if data.get("_v") == ANALYSIS_VERSION:
                return data
        except ValueError:
            pass
    data = build()
    data["_v"] = ANALYSIS_VERSION
    f.write_text(json.dumps(data))
    return data


def cached_only(m: dict, name: str) -> dict:
    """A cached analysis result, or AnalysisError when it has not been computed yet (never starts work)."""
    f = _cache_file(m, name)
    if f.exists():
        try:
            data = json.loads(f.read_text())
            if data.get("_v") == ANALYSIS_VERSION:
                return data
        except ValueError:
            pass
    raise AnalysisError(f"{name} has not been analysed yet")


def run_task(task: str, params: dict, progress: Progress = lambda f: None) -> dict:
    """Run backend.tasks in a child process (cancellable), streaming its PROGRESS lines."""
    with tempfile.TemporaryDirectory(prefix="ff_task_") as tmp:
        out = Path(tmp) / "result.json"
        cmd = [sys.executable, "-m", "backend.tasks", task, json.dumps({**params, "out": str(out)})]

        def on_line(line: str) -> None:
            if line.startswith("PROGRESS "):
                try:
                    progress(float(line.split()[1]))
                except ValueError:
                    pass

        res = run_streaming(cmd, on_line)
        if res.returncode != 0 or not out.exists():
            tail = [l for l in (res.stderr or "").strip().splitlines() if l.strip() and "objc[" not in l]
            raise AnalysisError(f"{task} failed: {tail[-1] if tail else 'exit code ' + str(res.returncode)}")
        return json.loads(out.read_text())


def _analysis_source(m: dict) -> Path:
    proxy = media_svc.proxy_path(m["id"])
    return proxy if proxy and proxy.exists() else media_svc.render_path(m["id"])


def scenes(m: dict, progress: Progress = lambda f: None) -> dict:
    return _cached(m, "scenes", lambda: run_task("scenes", {"path": str(_analysis_source(m))}, progress))


def visual_features(m: dict, progress: Progress = lambda f: None) -> dict:
    return _cached(m, "features", lambda: run_task("features", {"path": str(_analysis_source(m)), "step": 0.5},
                                                   progress))


def audio_features(m: dict) -> dict:
    def build() -> dict:
        if not m["has_audio"]:
            return {"silences": [], "energy": [], "step": 0.5}
        src = _analysis_source(m)
        try:
            silences = va.detect_silences(src, SILENCE_DB, SILENCE_MIN)
        except FFmpegError as e:
            raise AnalysisError(str(e).splitlines()[0])
        dur = float(m["duration"] or 0)
        return {"silences": [[round(a, 3), round(min(b, dur), 3)] for a, b in silences],
                "energy": va.audio_energy(src, 0.5), "step": 0.5}
    return _cached(m, "audio", build)


def transcript(m: dict, model: str, progress: Progress = lambda f: None, language: str = "auto") -> dict:
    """Cached per (media, model, language): re-generating captions never re-runs speech recognition."""
    if not m["has_audio"]:
        return {"cues": [], "language": None, "model": model}
    src = media_svc.render_path(m["id"])
    lang = (language or "auto").lower()
    name = f"transcript_{model}" if lang == "auto" else f"transcript_{model}_{lang}"
    return _cached(m, name, lambda: run_task("transcribe", {"path": str(src), "model": model, "language": lang},
                                             progress))


def media_rows(pid: str, kinds: tuple[str, ...]) -> list[dict]:
    marks = ",".join("?" * len(kinds))
    return db.query(f"SELECT * FROM media WHERE project_id=? AND kind IN ({marks}) ORDER BY position, created_at",
                    (pid, *kinds))
