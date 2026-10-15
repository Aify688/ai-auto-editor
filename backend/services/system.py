"""Dependency status, reported honestly so the UI never claims a feature it cannot run."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from video_editor import deps

from .. import config


@lru_cache(maxsize=1)
def ffmpeg_version() -> str | None:
    if not shutil.which("ffmpeg"):
        return None
    out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout
    return out.split("\n", 1)[0].replace("ffmpeg version ", "").split(" ")[0] or None


def whisper_model_cached(model: str) -> bool:
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    return (hub / f"models--Systran--faster-whisper-{model}").exists()


def status() -> dict:
    has = lambda m: importlib.util.find_spec(m) is not None  # noqa: E731
    ffmpeg_ok = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    whisper = has("faster_whisper")
    return {
        "ffmpeg": {"ok": ffmpeg_ok, "version": ffmpeg_version(),
                   "hint": None if ffmpeg_ok else "Install FFmpeg: brew install ffmpeg"},
        "sceneDetection": {"ok": has("scenedetect") and has("cv2"), "engine": "PySceneDetect (ContentDetector)",
                           "hint": "pip install 'scenedetect[opencv-headless]'"},
        "transcription": {"ok": whisper, "engine": f"faster-whisper ({config.WHISPER_MODEL}, local CPU)",
                          "modelCached": whisper_model_cached(config.WHISPER_MODEL),
                          "hint": None if whisper else "pip install faster-whisper"},
        "transitions": {"ok": not deps.check(["filter:xfade"])},
        "musicDucking": {"ok": not deps.check(["filter:sidechaincompress"])},
        "limits": {"maxUploadMb": config.MAX_UPLOAD_MB,
                   "extensions": sorted(e.lstrip(".") for e in config.ALLOWED_EXTS)},
        "dataDir": str(config.DATA_DIR),
    }
