"""Runtime configuration from environment variables (optionally a .env file).

Nothing secret is required to run FrameFlow; all processing is local.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.environ.get("FRAMEFLOW_DATA_DIR", ROOT / "data")).resolve()
DB_PATH = DATA_DIR / "frameflow.db"
PROJECTS_DIR = DATA_DIR / "projects"
MAX_UPLOAD_MB = int(os.environ.get("FRAMEFLOW_MAX_UPLOAD_MB", "4096"))
WHISPER_MODEL = os.environ.get("FRAMEFLOW_WHISPER_MODEL", "base")
FRONTEND_DIST = ROOT / "frontend" / "dist"
CORS_ORIGINS = [o for o in os.environ.get(
    "FRAMEFLOW_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o]

VIDEO_EXTS = {".mp4", ".mov", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
AUDIO_EXTS = {".mp3", ".wav"}
ALLOWED_EXTS = VIDEO_EXTS | IMAGE_EXTS | AUDIO_EXTS


def kind_for(ext: str) -> str | None:
    ext = ext.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def ensure_dirs() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
