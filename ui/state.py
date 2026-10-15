"""Session state + upload persistence shared by pages."""
from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from video_editor import settings


def init() -> None:
    ss = st.session_state
    if "workdir" not in ss:
        ss.workdir = tempfile.mkdtemp(prefix="ave_ui_")
    ss.setdefault("page", "workspace")
    # deep links: ?page=projects | dashboard | settings | workspace (applied once per session)
    if "page_linked" not in ss:
        ss.page_linked = True
        want = st.query_params.get("page")
        if want in ("workspace", "dashboard", "projects", "settings"):
            ss.page = want
    ss.setdefault("settings", settings.load())
    ss.setdefault("preset", ss.settings["default_preset"])
    ss.setdefault("last_preset_applied", None)


def workdir() -> Path:
    return Path(st.session_state.workdir)


def save_upload(f, sub: str) -> Path:
    d = workdir() / sub
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{abs(hash((f.name, f.size))) % 10**8}_{Path(f.name).name}"
    if not dest.exists():
        dest.write_bytes(f.getbuffer())
    return dest


def go(page: str) -> None:
    st.session_state.page = page
