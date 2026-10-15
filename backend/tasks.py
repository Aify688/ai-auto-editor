"""Heavy analysis tasks, run as child processes:  python -m backend.tasks <task> <args-json>

OpenCV and faster-whisper (PyAV) ship conflicting FFmpeg dylibs on macOS, so they are never
loaded into the API server process. Child processes also make cancellation a clean kill.
Each task prints `PROGRESS <0..1>` lines and writes its JSON result to args["out"].
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _progress(frac: float) -> None:
    print(f"PROGRESS {max(0.0, min(1.0, frac)):.4f}", flush=True)


# ----------------------------------------------------------------------- scenes
def scenes(args: dict) -> dict:
    """Shot boundaries with PySceneDetect's ContentDetector (HSV + edge change between frames)."""
    from scenedetect import ContentDetector, SceneManager, open_video

    video = open_video(args["path"])
    fps = float(video.frame_rate or 30.0)
    total = max(1, int(video.duration.get_frames()))
    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=float(args.get("threshold", 27.0)),
                                         min_scene_len=max(1, int(fps * float(args.get("min_len", 0.6))))))
    state = {"last": 0}

    def on_frame(frame_img, frame_num):  # called for every processed frame
        if frame_num - state["last"] >= 60:
            state["last"] = frame_num
            _progress(frame_num / total)

    manager.detect_scenes(video, callback=on_frame)
    found = manager.get_scene_list(start_in_scene=True)
    duration = video.duration.get_seconds()
    out = [[round(a.get_seconds(), 3), round(b.get_seconds(), 3)] for a, b in found]
    if not out:
        out = [[0.0, round(duration, 3)]]
    _progress(1.0)
    return {"scenes": out, "duration": duration, "detector": "PySceneDetect ContentDetector",
            "threshold": float(args.get("threshold", 27.0))}


# ----------------------------------------------------------------------- visual features
def features(args: dict) -> dict:
    """Per-step visual measurements with OpenCV: sharpness, motion, brightness, faces, motion centroid."""
    import cv2
    import numpy as np

    step = float(args.get("step", 0.5))
    cap = cv2.VideoCapture(args["path"])
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open {args['path']}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    every = max(1, int(round(fps * step)))
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    sharp, motion, bright, faces, centroid = [], [], [], [], []
    prev = None
    idx = 0
    sample = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % every == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            h, w = frame.shape[:2]
            scale = 320.0 / max(1, w)
            small = cv2.resize(frame, (320, max(2, int(h * scale))), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            sharp.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
            bright.append(float(gray.mean() / 255.0))
            tiny = cv2.resize(gray, (160, max(2, int(gray.shape[0] / 2))), interpolation=cv2.INTER_AREA)
            tiny = cv2.GaussianBlur(tiny, (5, 5), 0)
            if prev is None:
                motion.append(0.0)
                centroid.append(None)
            else:
                diff = cv2.absdiff(tiny, prev).astype(np.float32)
                m = float(diff.mean() / 255.0)
                motion.append(m)
                mask = diff > 18
                if mask.sum() > diff.size * 0.01:
                    ys, xs = np.nonzero(mask)
                    centroid.append([round(float(xs.mean() / diff.shape[1]), 3),
                                     round(float(ys.mean() / diff.shape[0]), 3)])
                else:
                    centroid.append(None)
            prev = tiny
            face = None
            if sample % 2 == 0:  # faces once per second is enough to steer cropping
                found = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=6, minSize=(24, 24))
                if len(found):
                    x, y, fw, fh = max(found, key=lambda f: f[2] * f[3])
                    face = [round((x + fw / 2) / gray.shape[1], 3), round((y + fh / 2) / gray.shape[0], 3),
                            round(fw / gray.shape[1], 3)]
            faces.append(face)
            sample += 1
            if nframes and sample % 20 == 0:
                _progress(idx / nframes)
        idx += 1
    cap.release()
    _progress(1.0)
    return {"step": step, "sharpness": sharp, "motion": motion, "brightness": bright, "faces": faces,
            "centroid": centroid}


# ----------------------------------------------------------------------- transcription
def transcribe(args: dict) -> dict:
    """Local speech-to-text with faster-whisper; word timestamps are regrouped into short caption cues."""
    from faster_whisper import WhisperModel

    model = WhisperModel(args.get("model", "base"), device="cpu", compute_type="int8")
    segments, info = model.transcribe(args["path"], vad_filter=True, word_timestamps=True)
    duration = float(getattr(info, "duration", 0) or 0)
    max_chars, max_len = int(args.get("max_chars", 42)), float(args.get("max_seconds", 3.5))
    cues: list[dict] = []
    for seg in segments:
        if duration:
            _progress(seg.end / duration)
        words = [w for w in (seg.words or []) if w.word.strip()]
        if not words:
            if seg.text.strip():
                cues.append({"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip()})
            continue
        cur: list = []
        for w in words:
            text = "".join(x.word for x in cur + [w]).strip()
            too_long = cur and (len(text) > max_chars or w.end - cur[0].start > max_len)
            if too_long:
                cues.append({"start": float(cur[0].start), "end": float(cur[-1].end),
                             "text": "".join(x.word for x in cur).strip()})
                cur = []
            cur.append(w)
            if w.word.strip()[-1:] in ".?!" and w.end - cur[0].start > 0.8:
                cues.append({"start": float(cur[0].start), "end": float(cur[-1].end),
                             "text": "".join(x.word for x in cur).strip()})
                cur = []
        if cur:
            cues.append({"start": float(cur[0].start), "end": float(cur[-1].end),
                         "text": "".join(x.word for x in cur).strip()})
    _progress(1.0)
    return {"language": getattr(info, "language", None), "duration": duration,
            "model": args.get("model", "base"), "cues": [c for c in cues if c["end"] > c["start"] and c["text"]]}


TASKS = {"scenes": scenes, "features": features, "transcribe": transcribe}

if __name__ == "__main__":
    name, raw = sys.argv[1], sys.argv[2]
    params = json.loads(raw)
    result = TASKS[name](params)
    Path(params["out"]).write_text(json.dumps(result))
