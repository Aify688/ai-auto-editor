"""Orchestrates the end-to-end process: probe -> plan -> normalize -> concat."""
from __future__ import annotations

import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import ffmpeg_ops, planner

ProgressCallback = Callable[[float, str], None]

OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "outputs"


def _noop_progress(fraction: float, message: str) -> None:
    pass


def process_videos(
    input_paths: list[Path],
    target_duration: float | None,
    aspect_choice: str,
    instructions_text: str = "",
    progress_cb: ProgressCallback = _noop_progress,
) -> Path:
    """Run the full basic-editing pipeline and return the final output path.

    Raises ffmpeg_ops.FFmpegError (or ValueError for bad input) on failure.
    Always cleans up its temporary working directory.
    """
    if not input_paths:
        raise ValueError("No input videos provided.")

    ffmpeg_ops.check_binaries()
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    work_dir = Path(tempfile.mkdtemp(prefix="ave_"))
    try:
        progress_cb(0.05, "Inspecting uploaded videos...")
        clips = [ffmpeg_ops.probe_video(p) for p in input_paths]

        target_w, target_h = planner.resolve_target_resolution(aspect_choice, clips)
        segments = planner.build_plan(clips, target_duration)

        segment_paths: list[Path] = []
        total = len(segments)
        for i, seg in enumerate(segments):
            frac = 0.1 + 0.75 * (i / total)
            progress_cb(frac, f"Processing clip {i + 1}/{total} ({seg.clip.path.name})...")
            seg_path = work_dir / f"segment_{i:03d}.mp4"
            ffmpeg_ops.process_segment(
                clip=seg.clip,
                start=seg.start,
                duration=seg.duration,
                target_w=target_w,
                target_h=target_h,
                output_path=seg_path,
            )
            segment_paths.append(seg_path)

        progress_cb(0.9, "Joining clips together...")
        output_path = _unique_output_path()
        ffmpeg_ops.concat_segments(segment_paths, output_path)

        _write_sidecar(output_path, clips, target_duration, aspect_choice, instructions_text)

        progress_cb(1.0, "Done.")
        return output_path
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _unique_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    return OUTPUTS_DIR / f"edited_{timestamp}_{unique_id}.mp4"


def _write_sidecar(
    output_path: Path,
    clips: list[ffmpeg_ops.ClipInfo],
    target_duration: float | None,
    aspect_choice: str,
    instructions_text: str,
) -> None:
    """Save the parameters used for this run next to the output video.

    The instructions text is stored for traceability only -- it is not
    currently used to influence editing decisions.
    """
    sidecar_path = output_path.with_suffix(".txt")
    lines = [
        f"Output: {output_path.name}",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Source clips: {', '.join(c.path.name for c in clips)}",
        f"Target duration: {target_duration if target_duration else 'full length'}",
        f"Aspect ratio: {aspect_choice}",
        "",
        "Editing instructions (not yet applied by an AI model -- the clips",
        "above were trimmed/combined using a fixed duration/aspect-ratio",
        "rule, not by interpreting this text):",
        instructions_text.strip() or "(none provided)",
    ]
    sidecar_path.write_text("\n".join(lines))
