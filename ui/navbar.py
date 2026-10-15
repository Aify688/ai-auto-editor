"""Top navigation bar for the non-workspace pages (Dashboard, My Projects, Settings)."""
from __future__ import annotations

import streamlit as st

from . import state

NAV = [("workspace", "Workspace", ":material/movie_edit:"),
       ("dashboard", "Dashboard", ":material/dashboard:"),
       ("projects", "My Projects", ":material/folder:"),
       ("settings", "Settings", ":material/settings:")]

LOGO = ('<svg width="34" height="34" viewBox="0 0 34 34"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#5aa0ff"/><stop offset="1" stop-color="#2a63e6"/></linearGradient></defs>'
        '<path d="M5 4.5c0-1.7 1.8-2.7 3.3-1.9l21 11.6c1.5.8 1.5 3 0 3.8l-21 11.6C6.8 29.4 5 28.400 5 26.700z" '
        'fill="url(#lg)"/></svg>')


def render(active: str) -> None:
    with st.container(key="pj_nav"):
        c = st.columns([2.6, 1.25, 1.25, 1.35, 1.2, 2.6], vertical_alignment="center")
        c[0].markdown(f'<div class="pj-brand">{LOGO}<span>AI Auto Editor</span></div>', unsafe_allow_html=True)
        for col, (key, label, icon) in zip(c[1:5], NAV):
            if col.button(label, icon=icon, key=f"nav_{key}", width="stretch",
                          type="primary" if active == key else "secondary"):
                state.go(key)
                st.rerun()
