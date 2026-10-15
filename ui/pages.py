"""The four pages: Dashboard, Create Video, My Projects, Settings."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import streamlit as st

from video_editor import library, pipeline, planner, presets, registry, settings, workspace
from video_editor.ffmpeg_ops import FFmpegError

from . import components as C, state


def _title(text: str, sub: str = "") -> None:
    st.title(text)
    if sub:
        st.markdown(f'<p class="ave-sub">{sub}</p>', unsafe_allow_html=True)


def projects() -> list[Path]:
    return [v.path for v in library.list_videos()]


def _plan_for(mp4: Path) -> dict:
    try:
        return json.loads(mp4.with_suffix(".plan.json").read_text())
    except (OSError, ValueError):
        return {}


# ============================================================ Dashboard
def dashboard() -> None:
    _title("Dashboard", "Turn raw footage into a finished video in one click.")
    items = projects()
    total = sum(C.clip_meta(str(p), p.stat().st_mtime)["duration"] for p in items)
    avail = sum(1 for c in registry.CAPS if c.available)
    c1, c2, c3 = st.columns(3)
    with c1:
        C.stat_card(str(len(items)), "Videos created", "movie")
    with c2:
        C.stat_card(C.fmt_dur(total), "Total runtime", "schedule")
    with c3:
        C.stat_card(str(avail), "Editing features ready", "auto_awesome")
    st.write("")
    if st.button("Open workspace", type="primary", icon=":material/add_circle:", key="dash_new"):
        state.go("workspace")
        st.rerun()
    C.label("Recent projects")
    if not items:
        st.caption("Nothing yet. Upload a video to get started.")
    else:
        cols = st.columns(4)
        for col, p in zip(cols, items[:4]):
            with col:
                C.thumb(p, p.stem.replace("edited_", ""))


# ============================================================ My Projects
def my_projects() -> None:
    from . import projects_page

    projects_page.render()


# ============================================================ Settings
def settings_page() -> None:
    _title("Settings")
    ss = st.session_state
    cur = ss.settings
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        preset = c1.selectbox("Default style", list(presets.PRESETS), index=list(presets.PRESETS).index(
            cur["default_preset"]), format_func=lambda k: presets.PRESETS[k].name)
        res = c2.selectbox("Export resolution", [720, 1080, 1440], index=[720, 1080, 1440].index(cur["short_edge"]))
        wm = c3.selectbox("Subtitle model", ["tiny", "base", "small", "medium"],
                          index=["tiny", "base", "small", "medium"].index(cur["whisper_model"]),
                          help="Larger models are more accurate and slower; downloaded on first use.")
        if st.button("Save settings", type="primary", icon=":material/save:"):
            ss.settings = {"default_preset": preset, "short_edge": res, "whisper_model": wm}
            settings.save(ss.settings)
            st.success("Saved.")
    with st.expander("Feature availability"):
        label = {"available": "Ready", "missing_dependency": "Missing dependency", "not_implemented": "Not built yet",
                 "external_tool": "Needs another tool", "broken_handler": "Broken"}
        st.dataframe([{"Feature": c.name, "Status": label[c.status()[0]], "Details": c.status()[1] or "—"}
                      for c in registry.CAPS], hide_index=True, width="stretch")
    with st.expander("Classic editor (original)"):
        st.caption("Even trim to a target length, aspect ratio, concatenate.")
        files = st.file_uploader("Clips", type=["mp4", "mov"], accept_multiple_files=True, key="cl_files")
        full = st.checkbox("Use full length", True, key="cl_full")
        tgt = None if full else st.number_input("Target duration (s)", 1.0, 3600.0, 30.0, key="cl_dur")
        asp = st.selectbox("Aspect ratio", list(planner.ASPECT_RATIOS) + [planner.MATCH_FIRST_CLIP], key="cl_asp")
        if st.button("Process", key="cl_go", disabled=not files):
            try:
                ss.classic_out = str(pipeline.process_videos([state.save_upload(f, "classic") for f in files], tgt, asp, ""))
            except (FFmpegError, ValueError) as ex:
                st.error(f"Processing failed: {ex}")
        if ss.get("classic_out") and Path(ss.classic_out).exists():
            st.video(ss.classic_out)
