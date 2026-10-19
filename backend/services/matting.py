"""AI background removal: person/foreground matting with temporal smoothing.

Model: MODNet "photographic portrait matting" (Apache-2.0, 25.9 MB ONNX), run through onnxruntime, which
the app already ships for faster-whisper, so no extra Python dependency.  ~100 ms per frame on an Apple
M4 (CPU), ~600 MB of RAM.  The file is downloaded once into data/models/ on first use and verified by hash.

The source video is never modified: a matte (grey video, same timeline as the preview proxy) is cached
under the project's cache folder, and FFmpeg composites foreground + new background at render time
(video_editor.engine.render_segment).  Audio is stream-copied through the same trim, so sync is kept.

Temporal consistency: the matte is inferred on every k-th frame, blended with the previous matte per pixel
(static areas are smoothed heavily, moving areas follow the new frame), reset on scene cuts, edge-firmed with a
smoothstep, and linearly interpolated for the frames in between.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import urllib.request
from pathlib import Path
from typing import Callable

from .. import config

MODEL_NAME = "modnet_photographic_portrait_matting.onnx"
MODEL_URL = ("https://huggingface.co/DavG25/modnet-pretrained-models/resolve/main/models/"
             "modnet_photographic_portrait_matting.onnx")
MODEL_SHA256 = "07c308cf0fc7e6e8b2065a12ed7fc07e1de8febb7dc7839d7b7f15dd66584df9"
MODEL_BYTES = 25_888_640
MODEL_LICENSE = "Apache-2.0 (MODNet, ZHKKKe/MODNet)"
MATTE_VERSION = 1
MATTE_WIDTH = 480          # width the matte is stored at; it is scaled to the video size when compositing
INFER_FPS = 15.0           # inference rate cap; frames in between are interpolated
REF_SIZE = 512             # longest side fed to the network

Progress = Callable[[float, str], None]


class MattingError(RuntimeError):
    """Expected failure with a message that can be shown to the user as-is."""


_lock = threading.Lock()
_session = None


# ------------------------------------------------------------------ model management
def model_path() -> Path:
    return config.DATA_DIR / "models" / MODEL_NAME


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def status() -> dict:
    """Capability probe for the UI: is the runtime importable and is the model already on disk?"""
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError as e:
        return {"ok": False, "engine": "MODNet (onnxruntime)", "modelCached": False,
                "hint": f"Missing Python package: {e.name}. Run: pip install onnxruntime opencv-python-headless numpy"}
    p = model_path()
    return {"ok": True, "engine": "MODNet portrait matting (onnxruntime)", "license": MODEL_LICENSE,
            "modelCached": p.exists() and p.stat().st_size == MODEL_BYTES, "downloadMb": round(MODEL_BYTES / 1e6, 1),
            "hint": None}


def ensure_model(progress: Progress = lambda f, m: None) -> Path:
    p = model_path()
    if p.exists() and p.stat().st_size == MODEL_BYTES:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    try:
        progress(0.0, f"Downloading the segmentation model ({MODEL_BYTES / 1e6:.0f} MB, one time)")
        req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "FrameFlow"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as out:
            total = int(r.headers.get("Content-Length") or MODEL_BYTES)
            done = 0
            while True:
                chunk = r.read(1 << 18)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                progress(min(1.0, done / total), "Downloading the segmentation model (one time)")
        if _sha256(tmp) != MODEL_SHA256:
            raise MattingError("The downloaded segmentation model failed its integrity check. Try again.")
        tmp.replace(p)
    except MattingError:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as e:  # network errors, disk full, ...
        tmp.unlink(missing_ok=True)
        raise MattingError(f"Could not download the background-removal model ({e}). Check your internet connection, "
                           f"or download {MODEL_URL} and save it as {p}.")
    return p


def _get_session():
    global _session
    with _lock:
        if _session is None:
            import onnxruntime as ort
            path = ensure_model()
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 4
            try:
                _session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
            except Exception as e:
                raise MattingError(f"The segmentation model could not be loaded: {e}")
        return _session


# ------------------------------------------------------------------ inference
def matte_frame(bgr, ref: int | None = None):
    """float32 alpha in [0, 1], same height/width as the BGR uint8 image."""
    import cv2
    import numpy as np

    sess = _get_session()
    h, w = bgr.shape[:2]
    scale = (ref or REF_SIZE) / max(h, w)
    nh, nw = max(32, int(h * scale) // 32 * 32), max(32, int(w * scale) // 32 * 32)
    x = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)[:, :, ::-1].astype(np.float32)
    x = ((x - 127.5) / 127.5).transpose(2, 0, 1)[None]
    with _lock:
        out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0, 0]
    return cv2.resize(np.clip(out, 0.0, 1.0), (w, h), interpolation=cv2.INTER_LINEAR)


def matte_refined(bgr, box=None):
    """Two-stage matting: a quick low-resolution pass finds the subject, then the network runs again on a crop
    around it, which keeps arms, hands and held objects that a single full-frame pass loses on wide shots.
    *box* is the previous (smoothed) subject box so the crop does not jitter between frames.
    Returns (alpha, new_box)."""
    import numpy as np

    h, w = bgr.shape[:2]
    coarse = matte_frame(bgr, ref=384)
    ys, xs = np.where(coarse > 0.4)
    if len(xs) < 0.002 * coarse.size:
        return coarse, None
    new = (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
    box = new if box is None else tuple(0.6 * o + 0.4 * n for o, n in zip(box, new))
    x0, y0, x1, y1 = box
    pad = 0.2 * max(x1 - x0, y1 - y0)
    x0, y0, x1, y1 = int(max(0, x0 - pad)), int(max(0, y0 - pad)), int(min(w, x1 + pad)), int(min(h, y1 + pad))
    if x1 - x0 < 32 or y1 - y0 < 32:
        return coarse, box
    out = np.zeros((h, w), dtype=np.float32)
    out[y0:y1, x0:x1] = matte_frame(bgr[y0:y1, x0:x1], ref=REF_SIZE)
    return out, box


def _firm(alpha):
    """Smoothstep between 0.2 and 0.55: removes the grey haze MODNet leaves in the background and fills
    slightly translucent interiors (faces, dark clothes) without hardening the edge."""
    import numpy as np

    s = np.clip((alpha - 0.20) / 0.35, 0.0, 1.0)
    return s * s * (3.0 - 2.0 * s)


def _clean(alpha):
    """Drop small stray blobs (furniture edges, reflections) that are not connected to the main subject and
    fill small holes inside it."""
    import cv2
    import numpy as np

    binary = (alpha > 0.5).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        return alpha
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep_ids = [i + 1 for i, a in enumerate(areas) if a >= 0.15 * areas.max()]
    keep = np.isin(labels, keep_ids).astype(np.uint8)
    near = cv2.dilate(keep, np.ones((9, 9), np.uint8))
    alpha = alpha * near
    # holes: background components fully enclosed by the subject and smaller than 2% of it
    inv = (keep == 0).astype(np.uint8)
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    limit = 0.02 * float(keep.sum())
    for i in range(1, n2):
        x, y, w, h, area = st2[i]
        if area < limit and x > 0 and y > 0 and x + w < alpha.shape[1] and y + h < alpha.shape[0]:
            alpha[lab2 == i] = 1.0
    return alpha


class TemporalSmoother:
    """Per-pixel motion-adaptive exponential smoothing of successive mattes."""

    def __init__(self) -> None:
        self.state = None
        self.prev_gray = None

    def step(self, matte, gray):
        import cv2
        import numpy as np

        g = gray.astype(np.float32)
        if self.state is None or self.prev_gray is None:
            self.state = matte
        else:
            diff = np.abs(g - self.prev_gray)
            if float(diff.mean()) > 28.0:                    # hard cut: no history
                self.state = matte
            else:
                moving = cv2.GaussianBlur(diff / 255.0, (0, 0), 3.0)
                a = np.clip(0.30 + 6.0 * moving, 0.30, 0.95)  # still areas keep 70% history, moving ones follow
                self.state = a * matte + (1.0 - a) * self.state
        self.prev_gray = g
        return cv2.GaussianBlur(_clean(_firm(self.state)), (0, 0), 0.8)


# ------------------------------------------------------------------ cached matte videos
def matte_path(m: dict) -> Path:
    return config.project_dir(m["project_id"]) / "cache" / f"{m['id']}_matte.mkv"


def _meta_path(m: dict) -> Path:
    return matte_path(m).with_suffix(".json")


def has_matte(m: dict) -> bool:
    p, meta = matte_path(m), _meta_path(m)
    if not (p.exists() and meta.exists()):
        return False
    try:
        d = json.loads(meta.read_text())
    except ValueError:
        return False
    return d.get("version") == MATTE_VERSION and d.get("sha") == MODEL_SHA256


def _source_for(m: dict) -> Path:
    from . import analysis
    return analysis._analysis_source(m)


def compute_matte(m: dict, progress: Progress = lambda f, msg: None, force: bool = False) -> Path:
    """Matte the whole video once (cached). Raises MattingError with an actionable message."""
    import cv2
    import numpy as np

    if m["kind"] != "video":
        raise MattingError("AI Background Removal works on video clips.")
    out = matte_path(m)
    if has_matte(m) and not force:
        return out
    st = status()
    if not st["ok"]:
        raise MattingError(st["hint"])
    ensure_model(lambda f, msg: progress(0.0, msg))
    src = _source_for(m)
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise MattingError(f"Could not open {m['name']} for analysis.")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or int((m["duration"] or 0) * fps)
    sw, sh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    mw = min(MATTE_WIDTH, sw)
    mw -= mw % 2
    mh = int(round(sh * mw / sw / 2)) * 2
    step = max(1, int(round(fps / INFER_FPS)))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part.mkv")
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{mw}x{mh}",
                            "-r", f"{fps:.5f}", "-i", "-", "-c:v", "ffv1", "-pix_fmt", "gray", str(tmp)],
                           stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    smoother = TemporalSmoother()
    last_idx, last_alpha = -1, None
    coverage = []
    box, prev_small = None, None

    def write(alpha) -> None:
        enc.stdin.write((np.clip(alpha, 0, 1) * 255).astype(np.uint8).tobytes())

    try:
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                small = cv2.resize(frame, (mw, mh), interpolation=cv2.INTER_AREA)
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                if prev_small is not None and float(np.abs(gray.astype(np.float32) - prev_small).mean()) > 28.0:
                    box = None                                         # scene cut: forget the subject box
                prev_small = gray.astype(np.float32)
                raw, box = matte_refined(small, box)
                alpha = smoother.step(raw, gray)
                coverage.append(float(alpha.mean()))
                if last_alpha is not None:
                    for j in range(last_idx + 1, idx):                 # interpolate skipped frames
                        w = (j - last_idx) / (idx - last_idx)
                        write((1 - w) * last_alpha + w * alpha)
                write(alpha)
                last_idx, last_alpha = idx, alpha
                if total:
                    progress(min(0.99, idx / total), f"Finding the subject in {m['name']}")
            idx += 1
        for _ in range(last_idx + 1, idx):                              # tail after the last inferred frame
            write(last_alpha)
        enc.stdin.close()
        err = enc.stderr.read().decode(errors="replace")
        enc.stderr.close()
        if enc.wait() != 0:
            raise MattingError(f"Could not write the subject matte: {err.strip().splitlines()[-1] if err.strip() else 'ffmpeg failed'}")
    except BaseException:
        try:
            enc.kill()
        except Exception:
            pass
        tmp.unlink(missing_ok=True)
        raise
    finally:
        cap.release()
    if not coverage or max(coverage) < 0.01:
        tmp.unlink(missing_ok=True)
        raise MattingError("No person or clear foreground subject was found in this video, so there is nothing "
                           "to keep. Try a clip where the subject is larger or better lit.")
    tmp.replace(out)
    _meta_path(m).write_text(json.dumps({"version": MATTE_VERSION, "sha": MODEL_SHA256, "fps": fps, "frames": idx,
                                         "width": mw, "height": mh, "meanCoverage": round(sum(coverage) / len(coverage), 4)}))
    progress(1.0, "Subject found")
    return out


# ------------------------------------------------------------------ preview (one frame, same compositing maths)
def _hex_bgr(value: str) -> tuple[int, int, int]:
    h = (value or "#00B140").lstrip("#")
    if len(h) != 6:
        h = "00B140"
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def blur_sigma(strength: float, width: int) -> float:
    """Gaussian sigma in pixels for a 0-100 strength; used identically by the preview and the renderer."""
    return max(0.5, strength / 100.0 * 0.03 * width)


def preview_frame(m: dict, t: float, bg: dict, background_frame=None, max_width: int = 960):
    """PNG bytes: frame at time *t* composited with the chosen background (no whole-video analysis needed)."""
    import cv2
    import numpy as np

    st = status()
    if not st["ok"]:
        raise MattingError(st["hint"])
    ensure_model()
    cap = cv2.VideoCapture(str(_source_for(m)))
    if not cap.isOpened():
        raise MattingError(f"Could not open {m['name']}.")
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise MattingError("Could not read a frame at that position.")
    h, w = frame.shape[:2]
    if w > max_width:
        frame = cv2.resize(frame, (max_width, int(h * max_width / w)), interpolation=cv2.INTER_AREA)
        h, w = frame.shape[:2]
    alpha = cv2.GaussianBlur(_clean(_firm(matte_refined(frame)[0])), (0, 0), 0.8)
    if float(alpha.mean()) < 0.01:
        raise MattingError("No person or clear foreground subject was found in this frame.")
    mode = bg.get("mode", "color")
    if mode == "blur":
        sigma = blur_sigma(float(bg.get("blur", 50)), w)
        back = cv2.GaussianBlur(frame, (0, 0), sigma).astype(np.float32)
    elif mode in ("image", "video") and background_frame is not None:
        bh, bw = background_frame.shape[:2]
        k = max(w / bw, h / bh)
        scaled = cv2.resize(background_frame, (int(np.ceil(bw * k)), int(np.ceil(bh * k))), interpolation=cv2.INTER_AREA)
        y0, x0 = (scaled.shape[0] - h) // 2, (scaled.shape[1] - w) // 2
        back = scaled[y0:y0 + h, x0:x0 + w].astype(np.float32)
    else:
        back = np.empty_like(frame, dtype=np.float32)
        back[:] = _hex_bgr(bg.get("color", "#00B140"))
    out = frame.astype(np.float32) * alpha[..., None] + back * (1 - alpha[..., None])
    ok, buf = cv2.imencode(".png", np.clip(out, 0, 255).astype(np.uint8))
    return buf.tobytes()
