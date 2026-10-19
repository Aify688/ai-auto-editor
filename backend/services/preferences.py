"""User preferences kept next to the data (data/preferences.json). Environment variables stay the defaults."""
from __future__ import annotations

import json
import os
import threading

from .. import config

# model -> (download size in MB, what it is good for)
WHISPER_MODELS = {
    "tiny": (75, "Fastest, least accurate"),
    "base": (145, "Fast, fine for clear speech"),
    "small": (480, "Recommended for most languages, including Chinese"),
    "medium": (1500, "Most accurate, slow on a laptop CPU"),
}
_PATH = config.DATA_DIR / "preferences.json"
_lock = threading.Lock()


def _read() -> dict:
    try:
        return json.loads(_PATH.read_text())
    except (OSError, ValueError):
        return {}


def whisper_model() -> str:
    m = _read().get("whisperModel") or os.environ.get("FRAMEFLOW_WHISPER_MODEL", "base")
    return m if m in WHISPER_MODELS else "base"


def get() -> dict:
    return {"whisperModel": whisper_model(),
            "whisperModels": [{"id": k, "sizeMb": v[0], "note": v[1]} for k, v in WHISPER_MODELS.items()]}


def update(patch: dict) -> dict:
    with _lock:
        cur = _read()
        if "whisperModel" in patch:
            if patch["whisperModel"] not in WHISPER_MODELS:
                raise ValueError(f"Unknown model '{patch['whisperModel']}'.")
            cur["whisperModel"] = patch["whisperModel"]
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(cur, indent=1))
    return get()
