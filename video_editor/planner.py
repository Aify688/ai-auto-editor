"""Deterministic (non-AI) editing plan.

Given a list of probed clips, a target total duration, and an aspect ratio,
decide what portion of each clip to keep and what resolution to normalize
everything to. No natural-language understanding happens here -- this is a
fixed, predictable algorithm.
"""
from __future__ import annotations

from dataclasses import dataclass

from .ffmpeg_ops import ClipInfo

# label -> (width, height)
ASPECT_RATIOS: dict[str, tuple[int, int]] = {
    "16:9 (Landscape, 1920x1080)": (1920, 1080),
    "9:16 (Vertical, 1080x1920)": (1080, 1920),
    "1:1 (Square, 1080x1080)": (1080, 1080),
    "4:5 (Portrait, 1080x1350)": (1080, 1350),
}
MATCH_FIRST_CLIP = "Match first clip's aspect ratio"

MIN_SEGMENT_DURATION = 0.3  # seconds


@dataclass
class Segment:
    clip: ClipInfo
    start: float
    duration: float


def resolve_target_resolution(aspect_choice: str, clips: list[ClipInfo]) -> tuple[int, int]:
    """Turn the user's aspect-ratio choice into a concrete (width, height)."""
    if aspect_choice in ASPECT_RATIOS:
        return ASPECT_RATIOS[aspect_choice]

    # MATCH_FIRST_CLIP: scale the first clip's own aspect ratio to a
    # reasonable max size (cap the long edge at 1920) and force even
    # dimensions, which libx264 requires.
    first = clips[0]
    w, h = first.width, first.height
    long_edge = max(w, h)
    scale = min(1.0, 1920 / long_edge) if long_edge else 1.0
    target_w = _round_even(w * scale)
    target_h = _round_even(h * scale)
    return target_w, target_h


def _round_even(value: float) -> int:
    v = int(round(value))
    return v if v % 2 == 0 else v + 1


def build_plan(clips: list[ClipInfo], target_duration: float | None) -> list[Segment]:
    """Decide the start/duration to use from each clip.

    - No target duration (None or <= 0): use each clip in full.
    - With a target duration: split it evenly across all clips, capped by
      each clip's own length, trimmed from the center of the clip.
    """
    if not clips:
        return []

    if target_duration is None or target_duration <= 0:
        return [Segment(clip=c, start=0.0, duration=c.duration) for c in clips]

    per_clip_budget = target_duration / len(clips)
    segments: list[Segment] = []
    for clip in clips:
        alloc = min(per_clip_budget, clip.duration)
        alloc = max(alloc, min(MIN_SEGMENT_DURATION, clip.duration))
        start = max(0.0, (clip.duration - alloc) / 2)
        segments.append(Segment(clip=clip, start=start, duration=alloc))
    return segments
