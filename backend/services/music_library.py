"""A small, real, properly-licensed background-music library for mood-based auto-selection.

Every track here is CC BY 4.0 (commercial use allowed, attribution required) from
https://github.com/tannerhelland/free-music — see backend/assets/music/CREDITS.md for the
full attribution and the (heuristic, audio-feature-based) mood-tagging methodology.

This module intentionally has no network access and invents nothing: it's a fixed catalog
of real files checked into backend/assets/music/, so "musicSource: library/auto" is only ever
offered because real tracks exist, never as a stand-in for ones that don't.
"""
from __future__ import annotations

from pathlib import Path

from .. import config

ASSET_DIR = config.ROOT / "backend" / "assets" / "music"

# id -> (mood, display title, original title, duration seconds)
_CATALOG = {
    "lib:cinematic": ("cinematic", "Crossroads", "Crossroads", 242.0),
    "lib:energetic": ("energetic", "Deserve to be Loved", "Deserve to be Loved", 206.0),
    "lib:relaxing": ("relaxing", "Home", "Home", 90.0),
    "lib:happy": ("happy", "Daybreak", "Daybreak", 114.0),
    "lib:dramatic": ("dramatic", "The Haunting", "The Haunting", 100.0),
}

ATTRIBUTION = "Music by Tanner Helland (CC BY 4.0) — https://github.com/tannerhelland/free-music"

# Which mood "auto" picks for each editing style, when the user hasn't chosen a mood explicitly.
# Purely a reasonable default pairing, not a claim about what the footage actually needs.
_STYLE_MOOD = {
    "dynamic": "energetic", "marketing": "energetic", "social": "happy", "vlog": "happy",
    "cinematic": "cinematic", "travel": "cinematic", "professional": "relaxing",
    "energetic": "energetic", "minimal": "relaxing", "documentary": "cinematic",
}


def is_library_id(media_id: str | None) -> bool:
    return bool(media_id) and media_id.startswith("lib:")


def by_mood(mood: str) -> dict | None:
    mid = f"lib:{mood}"
    row = _CATALOG.get(mid)
    if row is None:
        return None
    return {"id": mid, "mood": row[0], "title": row[1], "duration": row[3]}


def auto_mood(style: str) -> str:
    """Pick a mood for musicSource == "auto" based on the editing style. Defaults to "cinematic"
    for styles with no obvious pairing (including the meta-style "auto" itself)."""
    return _STYLE_MOOD.get(style, "cinematic")


def resolve_path(media_id: str) -> Path:
    row = _CATALOG.get(media_id)
    if row is None:
        raise KeyError(f"Unknown library track id: {media_id}")
    path = ASSET_DIR / f"{row[0]}.mp3"
    if not path.exists():
        raise FileNotFoundError(f"Library track file missing on disk: {path}")
    return path


def list_library() -> list[dict]:
    """Public-safe metadata for the API — a /music-library/ URL to preview/stream, no filesystem paths."""
    return [{"id": mid, "mood": mood, "title": title, "duration": dur, "attribution": ATTRIBUTION,
             "url": f"/music-library/{mood}.mp3"}
            for mid, (mood, title, _orig, dur) in _CATALOG.items()]
