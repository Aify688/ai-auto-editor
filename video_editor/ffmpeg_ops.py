"""Low-level wrappers around the ffmpeg / ffprobe binaries.

Everything here shells out to the system ffmpeg/ffprobe install. No video
decoding/encoding happens in Python.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


class FFmpegError(RuntimeError):
    """Raised when an ffmpeg/ffprobe subprocess fails."""


class Cancelled(FFmpegError):
    """Raised when the calling thread's cancel event is set while a subprocess runs."""


_local = threading.local()


def set_cancel_event(event: Optional[threading.Event]) -> None:
    """Make every subprocess started from this thread killable via `event`."""
    _local.cancel = event


def _cancel_event() -> Optional[threading.Event]:
    return getattr(_local, "cancel", None)


def check_cancelled() -> None:
    ev = _cancel_event()
    if ev is not None and ev.is_set():
        raise Cancelled("Cancelled by user")


def run_process(cmd: list[str], text: bool = True) -> subprocess.CompletedProcess:
    """subprocess.run(capture_output=True) that is killed if this thread's cancel event fires."""
    ev = _cancel_event()
    if ev is None:
        return subprocess.run(cmd, capture_output=True, text=text)
    check_cancelled()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text)
    while True:
        try:
            out, err = proc.communicate(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            if ev.is_set():
                proc.kill()
                proc.communicate()
                raise Cancelled("Cancelled by user")
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def run_streaming(cmd: list[str], on_line: Callable[[str], None]) -> subprocess.CompletedProcess:
    """Run `cmd`, calling `on_line` for each stdout line as it arrives. Cancellable like run_process."""
    check_cancelled()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    err_chunks: list[str] = []
    t_err = threading.Thread(target=lambda: err_chunks.append(proc.stderr.read()), daemon=True)
    t_err.start()

    def pump() -> None:
        for line in proc.stdout:
            on_line(line.rstrip("\n"))

    t_out = threading.Thread(target=pump, daemon=True)
    t_out.start()
    ev = _cancel_event()
    while proc.poll() is None:
        if ev is not None and ev.is_set():
            proc.kill()
            proc.wait()
            raise Cancelled("Cancelled by user")
        t_out.join(timeout=0.25)
    t_out.join()
    t_err.join()
    proc.stdout.close()
    proc.stderr.close()
    return subprocess.CompletedProcess(cmd, proc.returncode, "", "".join(err_chunks))


@dataclass
class ClipInfo:
    path: Path
    duration: float
    width: int
    height: int
    has_audio: bool
    fps: float


def check_binaries() -> None:
    """Raise a clear error if ffmpeg/ffprobe are not on PATH."""
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if missing:
        raise FFmpegError(
            f"Missing required binaries: {', '.join(missing)}. "
            "Install FFmpeg (e.g. `brew install ffmpeg` on macOS) and ensure "
            "it is on your PATH."
        )


def probe_video(path: Path) -> ClipInfo:
    """Inspect a video file with ffprobe and return key properties."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = run_process(cmd)
    if result.returncode != 0:
        raise FFmpegError(f"ffprobe failed for {path.name}:\n{result.stderr.strip()}")

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    if not video_streams:
        raise FFmpegError(f"{path.name} has no video stream.")

    vstream = video_streams[0]
    width = int(vstream.get("width", 0))
    height = int(vstream.get("height", 0))

    # Duration can be missing on the video stream for some containers (MOV);
    # fall back to the container-level duration.
    duration_raw = vstream.get("duration") or data.get("format", {}).get("duration")
    if duration_raw is None:
        raise FFmpegError(f"Could not determine duration for {path.name}.")
    duration = float(duration_raw)

    fps = _parse_frame_rate(vstream.get("avg_frame_rate") or vstream.get("r_frame_rate"))

    return ClipInfo(
        path=path,
        duration=duration,
        width=width,
        height=height,
        has_audio=bool(audio_streams),
        fps=fps,
    )


def _parse_frame_rate(raw: str | None) -> float:
    if not raw:
        return 30.0
    try:
        if "/" in raw:
            num, den = raw.split("/")
            den = float(den)
            return float(num) / den if den else 30.0
        return float(raw)
    except (ValueError, ZeroDivisionError):
        return 30.0


def process_segment(
    clip: ClipInfo,
    start: float,
    duration: float,
    target_w: int,
    target_h: int,
    output_path: Path,
    fps: int = 30,
) -> None:
    """Trim [start, start+duration) from `clip`, normalize it to a common
    resolution/fps/audio format, and write it to `output_path`.

    Normalizing every segment identically lets us concatenate them with a
    lossless stream copy afterwards.
    """
    vfilter = (
        f"scale=w={target_w}:h={target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h},"
        f"fps={fps},"
        "format=yuv420p"
    )

    base_cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-t", f"{duration:.3f}",
        "-i", str(clip.path),
    ]

    if clip.has_audio:
        cmd = base_cmd + [
            "-vf", vfilter,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-ar", "44100", "-ac", "2", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]
    else:
        # Synthesize a silent stereo track so every segment has matching
        # audio streams and concat works regardless of source audio.
        cmd = base_cmd + [
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf", vfilter,
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]

    _run(cmd, f"processing segment from {clip.path.name}")


def concat_segments(segment_paths: list[Path], output_path: Path) -> None:
    """Join pre-normalized segments with a lossless stream copy."""
    if not segment_paths:
        raise FFmpegError("No segments to concatenate.")

    list_file = output_path.with_suffix(".txt")
    with open(list_file, "w") as f:
        for seg in segment_paths:
            escaped = str(seg).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    try:
        _run(cmd, "concatenating segments")
    finally:
        list_file.unlink(missing_ok=True)


def _run(cmd: list[str], action: str) -> None:
    result = run_process(cmd)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-20:])
        raise FFmpegError(f"ffmpeg failed while {action}:\n{tail}")
