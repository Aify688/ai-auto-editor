"""Dependency status, reported honestly so the UI never claims a feature it cannot run."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path

from video_editor import deps

from .. import config
from . import matting, preferences, textvideo


@lru_cache(maxsize=1)
def ffmpeg_version() -> str | None:
    if not shutil.which("ffmpeg"):
        return None
    out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout
    return out.split("\n", 1)[0].replace("ffmpeg version ", "").split(" ")[0] or None


def whisper_model_cached(model: str) -> bool:
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    return (hub / f"models--Systran--faster-whisper-{model}").exists()


def _code_mtime() -> float:
    root = config.ROOT
    newest = 0.0
    for folder in ("backend", "video_editor"):
        for p in (root / folder).rglob("*.py"):
            try:
                newest = max(newest, p.stat().st_mtime)
            except OSError:
                pass
    return newest


_BOOT_CODE = _code_mtime()
_stale_cache: tuple[float, bool] = (0.0, False)


def server_is_stale() -> bool:
    """True when the Python code on disk is newer than the code this process loaded: the app was updated but the
    server was not restarted, so new endpoints would be missing."""
    global _stale_cache
    now = time.time()
    if now - _stale_cache[0] > 3:
        _stale_cache = (now, _code_mtime() > _BOOT_CODE + 1)
    return _stale_cache[1]


def status() -> dict:
    has = lambda m: importlib.util.find_spec(m) is not None  # noqa: E731
    ffmpeg_ok = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    whisper = has("faster_whisper")
    return {
        "ffmpeg": {"ok": ffmpeg_ok, "version": ffmpeg_version(),
                   "hint": None if ffmpeg_ok else "Install FFmpeg: brew install ffmpeg"},
        "sceneDetection": {"ok": has("scenedetect") and has("cv2"), "engine": "PySceneDetect (ContentDetector)",
                           "hint": "pip install 'scenedetect[opencv-headless]'"},
        "transcription": {"ok": whisper, "engine": f"faster-whisper ({preferences.whisper_model()}, local CPU)",
                          "modelCached": whisper_model_cached(preferences.whisper_model()),
                          "hint": None if whisper else "pip install faster-whisper"},
        "backgroundRemoval": matting.status(),
        "textToVideo": textvideo.status(),
        "transitions": {"ok": not deps.check(["filter:xfade"])},
        "musicDucking": {"ok": not deps.check(["filter:sidechaincompress"])},
        "limits": {"maxUploadMb": config.MAX_UPLOAD_MB,
                   "extensions": sorted(e.lstrip(".") for e in config.ALLOWED_EXTS)},
        "dataDir": str(config.DATA_DIR),
        "server": {"stale": server_is_stale()},
    }
