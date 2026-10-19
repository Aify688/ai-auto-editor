"""Image to animation: one still image -> a short animated clip, made by a real image-to-video provider.

Uses the same Replicate-style prediction API as text-to-video (create -> poll -> download). Nothing here fakes
output: with no provider configured the request is refused with the setup steps, and provider errors are shown as
they are. The token stays on the server. The original image is never modified; the result is a new media item.

Duration and aspect ratio are enforced here, after generation (trim / centre-crop with FFmpeg), because providers
fix their own clip length and shape. The provider only receives the image and the motion prompt unless the
FRAMEFLOW_I2V_INPUT template asks for more ({aspect}, {seconds}, {motion}).
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from . import media as media_svc
from . import textvideo
from ..workers.jobs import JobFailed

DEFAULT_MODEL = "wan-video/wan-2.2-i2v-fast"
SETUP_HINT = ("Image to Animation needs an image-to-video provider. Add REPLICATE_API_TOKEN=<your token> to the .env "
              "file in the project folder (optionally FRAMEFLOW_I2V_MODEL and FRAMEFLOW_I2V_INPUT), then restart "
              "./start.sh.")
ASPECTS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:5": 4 / 5}
INTENSITY = {
    "low": "very subtle, calm motion",
    "medium": "natural, moderate motion",
    "high": "lively, pronounced motion",
}
KEEP = ("Keep the subject's identity, face, proportions, clothing and the original visual style exactly as in the "
        "image; no new objects, no text, no scene cuts.")
MAX_EDGE = 1280


def _cfg() -> dict:
    env = os.environ.get
    return {"model": env("FRAMEFLOW_I2V_MODEL", DEFAULT_MODEL).strip(),
            "input": env("FRAMEFLOW_I2V_INPUT", '{"image": "{image}", "prompt": "{prompt}"}')}


def status() -> dict:
    """Public status for the UI. Never includes the token."""
    ok = bool(textvideo._cfg()["token"])
    return {"configured": ok, "provider": "Replicate", "model": _cfg()["model"],
            "aspects": list(ASPECTS), "minSeconds": 2, "maxSeconds": 10, "hint": None if ok else SETUP_HINT}


def describe(path: Path) -> str:
    """What the image shows, as far as local analysis can tell: used to write a motion prompt when the user gave none."""
    try:
        import cv2
        img = cv2.imread(str(path))
        if img is not None:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            if len(cascade.detectMultiScale(gray, 1.15, 5, minSize=(max(24, gray.shape[1] // 25),) * 2)):
                return "person"
    except Exception:
        pass
    return "scene"


def build_prompt(user_prompt: str, intensity: str, subject: str) -> str:
    level = INTENSITY.get(intensity, INTENSITY["medium"])
    user_prompt = (user_prompt or "").strip()
    if user_prompt:
        motion = f"{user_prompt.rstrip('.')}. Motion style: {level}."
    elif subject == "person":
        motion = (f"The person moves naturally: gentle breathing, soft blinks, slight head and hair movement, fabric "
                  f"swaying a little. A slow cinematic camera push-in with soft depth parallax; background elements "
                  f"drift gently. Motion style: {level}.")
    else:
        motion = (f"Bring the scene to life: wind and water move, clouds or light drift, foreground and background "
                  f"separate with soft depth parallax, and a slow cinematic camera move. Motion style: {level}.")
    return f"{motion} {KEEP}"


def prepare_image(path: Path) -> str:
    """A JPEG data URI no larger than MAX_EDGE on its long side (the original file is left alone)."""
    with tempfile.TemporaryDirectory(prefix="ave_i2v_") as tmp:
        out = Path(tmp) / "in.jpg"
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-vf",
                            f"scale='min({MAX_EDGE},iw)':'min({MAX_EDGE},ih)':force_original_aspect_ratio=decrease",
                            "-frames:v", "1", "-q:v", "3", str(out)], capture_output=True, text=True, timeout=60)
        if r.returncode != 0 or not out.exists():
            raise JobFailed("The image could not be read. Try a JPG or PNG.")
        return "data:image/jpeg;base64," + base64.b64encode(out.read_bytes()).decode()


def provider_input(image_uri: str, prompt: str, aspect: str, seconds: float, intensity: str) -> dict:
    try:
        tpl = json.loads(_cfg()["input"])
    except ValueError:
        raise JobFailed("FRAMEFLOW_I2V_INPUT in .env is not valid JSON.")
    values = {"{image}": image_uri, "{prompt}": prompt, "{aspect}": aspect, "{seconds}": seconds, "{motion}": intensity}
    return textvideo._fill(tpl, values)


def fetch(url: str, dest: Path) -> None:
    """Download the provider's file and check it is a playable video before using it."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=120) as r, open(dest, "wb") as fh:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise JobFailed(f"Could not download the generated video: {getattr(e, 'reason', e)}")
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name",
                            "-of", "csv=p=0", str(dest)], capture_output=True, text=True)
    if probe.returncode != 0 or not probe.stdout.strip():
        raise JobFailed("The provider returned something that is not a playable video.")


def finish(src: Path, dst: Path, seconds: float, aspect: str) -> None:
    """Trim to the requested length and centre-crop to the requested shape. Never longer than the provider made it."""
    vf = ["setsar=1"]
    if aspect in ASPECTS:
        ar = ASPECTS[aspect]
        vf = [f"crop='if(gt(iw/ih,{ar}),trunc(ih*{ar}/2)*2,iw)':'if(gt(iw/ih,{ar}),ih,trunc(iw/{ar}/2)*2)'", "setsar=1"]
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-t", f"{seconds:.2f}", "-vf", ",".join(vf),
                        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(dst)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not dst.exists():
        raise JobFailed(f"The generated video could not be finished: {r.stderr.strip()[-200:]}")


def animate(pid: str, media_id: str, user_prompt: str, seconds: float, aspect: str, intensity: str, progress, check) -> dict:
    """Run the whole pipeline. `progress(fraction, message)`; `check()` raises when the user cancels."""
    row = media_svc.get_row(media_id)
    if row is None or row["project_id"] != pid or row["kind"] != "image":
        raise JobFailed("Choose an image from this project's media.")
    if row["status"] != "ready":
        raise JobFailed("The image is still processing. Try again in a moment.")
    original = media_svc.absolute(row["path"])
    progress(0.02, "Analyzing the image")
    prompt = build_prompt(user_prompt, intensity, describe(original))
    uri = prepare_image(original)
    progress(0.08, "Generating motion with AI")
    body = provider_input(uri, prompt, aspect, seconds, intensity)
    url = textvideo.generate_scene(prompt, aspect, check, model=_cfg()["model"], body=body, setup_hint=SETUP_HINT)
    progress(0.85, "Downloading the animation")
    stem = Path(row["name"]).stem[:40]
    with tempfile.TemporaryDirectory(prefix="ave_i2v_out_") as tmp:
        raw = Path(tmp) / "provider.mp4"
        fetch(url, raw)
        progress(0.92, "Trimming and framing")
        out = Path(tmp) / f"Animation - {stem}.mp4"
        finish(raw, out, seconds, aspect)
        with open(out, "rb") as fh:
            item = media_svc.save_upload(pid, out.name, fh)
    media_svc.process(item["id"])
    item = media_svc.get_row(item["id"])
    if item["status"] != "ready":
        raise JobFailed(f"The animation was generated but could not be processed: {item.get('error') or 'unknown error'}")
    return {"mediaId": item["id"], "name": item["name"], "duration": item["duration"], "prompt": prompt,
            "sourceMediaId": media_id}
