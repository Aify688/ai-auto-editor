"""Dependency probes.

A capability is only "available" when every dependency it lists passes its
probe here. Probes are cached and cheap; nothing is assumed.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable


@dataclass(frozen=True)
class Dependency:
    id: str
    label: str
    probe: Callable[[], bool]
    hint: str


@lru_cache(maxsize=1)
def _ffmpeg_filters() -> frozenset[str]:
    if shutil.which("ffmpeg") is None:
        return frozenset()
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True
    ).stdout
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) <= 3 and parts[0][0] in "T.":
            names.add(parts[1])
    return frozenset(names)


def _filter(name: str) -> Callable[[], bool]:
    return lambda: name in _ffmpeg_filters()


def _module(name: str) -> Callable[[], bool]:
    return lambda: importlib.util.find_spec(name) is not None


def _anthropic() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and importlib.util.find_spec("anthropic") is not None


DEPENDENCIES: dict[str, Dependency] = {d.id: d for d in [
    Dependency("ffmpeg", "FFmpeg + ffprobe", lambda: bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
               "brew install ffmpeg"),
    Dependency("pillow", "Pillow (caption/title rendering)", _module("PIL"), "pip install Pillow"),
    Dependency("numpy", "NumPy (audio/visual analysis)", _module("numpy"), "pip install numpy"),
    Dependency("filter:xfade", "FFmpeg xfade filter", _filter("xfade"), "FFmpeg >= 4.3"),
    Dependency("filter:sidechaincompress", "FFmpeg sidechaincompress filter", _filter("sidechaincompress"), "FFmpeg build"),
    Dependency("filter:afftdn", "FFmpeg afftdn filter", _filter("afftdn"), "FFmpeg build"),
    Dependency("filter:lut3d", "FFmpeg lut3d filter", _filter("lut3d"), "FFmpeg build"),
    Dependency("filter:vidstabdetect", "FFmpeg built with libvidstab", _filter("vidstabdetect"),
               "brew reinstall ffmpeg with --enable-libvidstab (or use a build that includes it)"),
    Dependency("faster_whisper", "faster-whisper (speech-to-text)", _module("faster_whisper"),
               "pip install faster-whisper"),
    Dependency("librosa", "librosa (beat detection)", _module("librosa"), "pip install librosa"),
    Dependency("anthropic_api", "Anthropic SDK + ANTHROPIC_API_KEY", _anthropic,
               "pip install anthropic and set ANTHROPIC_API_KEY"),
]}


def check(dep_ids: list[str]) -> list[str]:
    """Return human-readable descriptions of the dependencies that are missing."""
    missing = []
    for dep_id in dep_ids:
        dep = DEPENDENCIES[dep_id]
        if not dep.probe():
            missing.append(f"{dep.label} ({dep.hint})")
    return missing
