"""Small persisted user settings (JSON next to the project)."""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "user_settings.json"
DEFAULTS = {"default_preset": "shorts", "short_edge": 1080, "whisper_model": "base"}


def load() -> dict:
    try:
        return {**DEFAULTS, **json.loads(PATH.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(values: dict) -> None:
    PATH.write_text(json.dumps({**DEFAULTS, **values}, indent=2))
