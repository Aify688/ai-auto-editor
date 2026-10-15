"""Reusable UI pieces."""
from __future__ import annotations

import html
import subprocess
from pathlib import Path

import streamlit as st

from video_editor import ffmpeg_ops


def label(text: str) -> None:
    st.markdown(f'<div class="ave-label">{html.escape(text)}</div>', unsafe_allow_html=True)


def chips(items: list[tuple[str, str]], muted: bool = False) -> None:
    """items: (material icon name, text). Rendered as small pills."""
    cls = "ave-chip mute" if muted else "ave-chip"
    st.markdown("".join(f'<span class="{cls}">{html.escape(t)}</span>' for _, t in items), unsafe_allow_html=True)


@st.cache_data(show_spinner=False, max_entries=256)
def thumbnail(path: str, mtime: float, t: float = 0.8) -> bytes | None:
    cmd = ["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-vf", "scale=480:-2",
           "-f", "mjpeg", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode or not r.stdout:
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-frames:v", "1", "-vf", "scale=480:-2",
                            "-f", "mjpeg", "-"], capture_output=True)
    return r.stdout or None


@st.cache_data(show_spinner=False, max_entries=256)
def clip_meta(path: str, mtime: float) -> dict:
    try:
        c = ffmpeg_ops.probe_video(Path(path))
        return {"duration": c.duration, "w": c.width, "h": c.height, "audio": c.has_audio}
    except ffmpeg_ops.FFmpegError:
        return {"duration": 0.0, "w": 0, "h": 0, "audio": False}


def fmt_dur(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def thumb(path: Path, caption: str | None = None) -> None:
    """Responsive thumbnail (plain <img>, so it always fills its column)."""
    import base64
    img = thumbnail(str(path), path.stat().st_mtime)
    if img:
        b64 = base64.b64encode(img).decode()
        cap = f'<div class="ave-statl">{html.escape(caption)}</div>' if caption else ""
        st.markdown(f'<img src="data:image/jpeg;base64,{b64}" style="width:100%;border-radius:10px;display:block">{cap}',
                    unsafe_allow_html=True)
    else:
        st.caption(caption or path.name)


def stat_card(value: str, name: str, icon: str) -> None:
    with st.container(border=True):
        st.markdown(f":material/{icon}:")
        st.markdown(f'<div class="ave-stat">{html.escape(value)}</div><div class="ave-statl">{html.escape(name)}</div>',
                    unsafe_allow_html=True)


def steps_list(steps: list[tuple[str, str, str]], active: str | None, done_all: bool = False) -> str:
    """HTML for the processing steps. `active` is the current event key."""
    keys = [s[0] for s in steps]
    idx = keys.index(active) if active in keys else -1
    out = ['<ul class="ave-steps">']
    for i, (k, text, _) in enumerate(steps):
        state = "done" if done_all or i < idx else "active" if i == idx else ""
        dot = "✓" if state == "done" else ""
        out.append(f'<li class="{state}"><span class="dot">{dot}</span>{html.escape(text)}</li>')
    out.append("</ul>")
    return "".join(out)
