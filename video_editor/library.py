"""Rendered-video library: titles, metadata and safe deletion for files in outputs/."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import engine

SIDECAR_SUFFIXES = (".plan.json", ".edl", ".txt", ".frameflow.json")


def outputs_dir() -> Path:
    return engine.OUTPUTS_DIR


def _titles_file() -> Path:
    return outputs_dir() / "titles.json"


def _read_titles() -> dict:
    try:
        return json.loads(_titles_file().read_text())
    except (OSError, ValueError):
        return {}


def plan_for(video: Path) -> dict:
    try:
        return json.loads(video.with_suffix(".plan.json").read_text())
    except (OSError, ValueError):
        return {}


@dataclass
class Video:
    path: Path
    title: str
    created: float
    plan: dict

    @property
    def project_id(self) -> str | None:
        return self.plan.get("project_id")


def default_title(plan: dict) -> str:
    from . import presets

    if plan.get("mode") == "editor" and plan.get("goal"):
        return str(plan["goal"])
    style = presets.PRESETS.get(plan.get("preset", ""))
    return style.name if style else "Custom edit"


def list_videos() -> list[Video]:
    out_dir = outputs_dir()
    if not out_dir.exists():
        return []
    titles = _read_titles()
    items = []
    for p in out_dir.glob("*.mp4"):
        plan = plan_for(p)
        items.append(Video(p, titles.get(p.name) or default_title(plan), p.stat().st_mtime, plan))
    return sorted(items, key=lambda v: v.created, reverse=True)


def rename_video(path: Path, title: str) -> None:
    title = title.strip()
    if not title:
        raise ValueError("The name can't be empty.")
    titles = _read_titles()
    titles[path.name] = title[:120]
    _titles_file().write_text(json.dumps(titles, indent=1))


def delete_video(path: Path) -> list[str]:
    """Delete one rendered video and its generated sidecar files. Returns the removed file names."""
    path = Path(path).resolve()
    if path.parent != outputs_dir().resolve() or path.suffix.lower() != ".mp4":
        raise ValueError("Only rendered videos in the outputs folder can be deleted.")
    removed = []
    for f in [path] + [path.with_name(path.stem + s) for s in SIDECAR_SUFFIXES]:
        if f.exists():
            f.unlink()
            removed.append(f.name)
    titles = _read_titles()
    if titles.pop(path.name, None) is not None:
        _titles_file().write_text(json.dumps(titles, indent=1))
    return removed


def completed_project_ids() -> set[str]:
    return {v.project_id for v in list_videos() if v.project_id}
