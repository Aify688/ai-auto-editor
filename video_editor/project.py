"""Project-level features: plan persistence and EDL export."""
from __future__ import annotations

import json
from pathlib import Path


def save_plan(plan: dict, path: Path) -> Path:
    path.write_text(json.dumps(plan, indent=2))
    return path


def load_plan(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def _tc(seconds: float, fps: int) -> str:
    frames = int(round(seconds * fps))
    h, rem = divmod(frames, 3600 * fps)
    m, rem = divmod(rem, 60 * fps)
    s, f = divmod(rem, fps)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def export_edl(timeline: list[dict], names: list[str], fps: int, path: Path, title: str = "AI Auto Video Editor") -> Path:
    """CMX3600 EDL from engine timeline entries {clip,start,end,out_start,out_end}."""
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    for i, t in enumerate(timeline, 1):
        reel = (Path(names[t["clip"]]).stem[:8].upper().replace(" ", "_") or "AX")
        lines.append(f"{i:03d}  {reel:<8} V     C        {_tc(t['start'], fps)} {_tc(t['end'], fps)} "
                     f"{_tc(t['out_start'], fps)} {_tc(t['out_end'], fps)}")
        lines.append(f"* FROM CLIP NAME: {Path(names[t['clip']]).name}")
    path.write_text("\n".join(lines) + "\n")
    return path
