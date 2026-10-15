"""Generate deterministic sample clips (no downloads) into sample_videos/.

speech_pauses.mp4 : 8 s, 1280x720, tone "speech" bursts with 3 silent gaps
second_clip.mp4   : 5 s, 1280x720, different picture, steady tone
speech_pauses.srt : captions timed to the bursts
"""
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "sample_videos"

# tone is audible except inside these gaps (seconds)
GAPS = [(1.5, 3.0), (4.5, 5.2), (6.5, 7.0)]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr[-800:])


def main():
    OUT.mkdir(exist_ok=True)
    gate = "+".join(f"between(t,{a},{b})" for a, b in GAPS)
    run(["ffmpeg", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=8",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration=8,volume='if({gate},0,0.6)':eval=frame",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(OUT / "speech_pauses.mp4")])
    run(["ffmpeg", "-y",
         "-f", "lavfi", "-i", "mandelbrot=size=1280x720:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=330:duration=5",
         "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         str(OUT / "second_clip.mp4")])
    (OUT / "speech_pauses.srt").write_text(
        "1\n00:00:00,200 --> 00:00:01,400\nWelcome to the demo\n\n"
        "2\n00:00:03,100 --> 00:00:04,400\nThis part follows a pause\n\n"
        "3\n00:00:05,300 --> 00:00:06,400\nAnd here is another point\n\n"
        "4\n00:00:07,100 --> 00:00:07,900\nThanks for watching\n")
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
