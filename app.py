"""AI Auto Video Editor -- Streamlit app shell.

One unified workspace (ui/workspace_page.py) plus Dashboard / My Projects / Settings behind a shared
top navigation bar (ui/navbar.py). Editing logic lives in video_editor/.
"""
import streamlit as st

from ui import navbar, pages, projects_page, state, theme, workspace_page

st.set_page_config(page_title="AI Auto Video Editor", page_icon="🎬", layout="wide",
                   initial_sidebar_state="collapsed")
state.init()
theme.apply()

# Legacy page names from earlier sessions/links map to the unified workspace.
if st.session_state.page in ("create", "editor"):
    st.session_state.page = "workspace"
page = st.session_state.page

if page == "workspace":
    workspace_page.render()
else:
    theme.page_css()
    if page == "projects":
        projects_page.render()
    else:
        navbar.render(page)
        with st.container(key="pj_page"):
            {"dashboard": pages.dashboard, "settings": pages.settings_page}[page]()
