"""My Projects: editor projects and rendered videos, built from real project/output data."""
from __future__ import annotations

import base64
import html
from datetime import datetime
from pathlib import Path

import streamlit as st

from video_editor import library, workspace

from . import components as C
from . import navbar, state

FILTERS = ["All projects", "Draft", "In progress", "Completed"]
SORTS = ["Last updated", "Oldest first", "Name A–Z", "Name Z–A"]
PER_ROW = 3

ICON = {
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "clips": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "calendar": '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
    "play": '<polygon points="6 3 20 12 6 21 6 3" fill="currentColor"/>',
    "playc": '<circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/>',
    "film": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 3v18"/><path d="M3 7.5h4"/><path d="M3 12h18"/><path d="M3 16.5h4"/><path d="M17 3v18"/><path d="M17 7.5h4"/><path d="M17 16.5h4"/>',
}


def _svg(name: str, size: int = 15) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{ICON[name]}</svg>')


def _when(ts: float) -> str:
    return f"{datetime.fromtimestamp(ts):%b %d, %H:%M}"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _img(data: bytes | None) -> str:
    if not data:
        return f'<div class="pj-ph">{_svg("film", 30)}</div>'
    return f'<img src="data:image/jpeg;base64,{base64.b64encode(data).decode()}" alt="">'


def _meta(items: list[tuple[str, str]]) -> str:
    return '<div class="pj-meta">' + '<b class="sep"></b>'.join(
        f'<span>{_svg(i)}{html.escape(t)}</span>' for i, t in items) + '</div>'


# ------------------------------------------------------------------ data
def _cover(p: workspace.Project) -> bytes | None:
    """Thumbnail from the project's own first clip; None (placeholder) when media is missing."""
    seg = p.segments[0] if p.segments else None
    idx = seg["clip"] if seg else 0
    if idx >= len(p.sources):
        return None
    src = Path(p.sources[idx])
    if not src.exists():
        return None
    t = (seg["start"] + 0.4) if seg else 0.8
    return C.thumbnail(str(src), src.stat().st_mtime, round(t, 1))


def gather() -> dict:
    completed = library.completed_project_ids()
    projects, unreadable = [], 0
    for path in workspace.Project.list_saved():
        try:
            p = workspace.Project.load(path)
        except (OSError, ValueError, KeyError):
            unreadable += 1
            continue
        projects.append({"path": path, "p": p, "name": p.name, "ts": path.stat().st_mtime,
                         "status": p.status(completed), "cover": _cover(p)})
    videos = []
    for v in library.list_videos():
        meta = C.clip_meta(str(v.path), v.created)
        videos.append({"v": v, "name": v.title, "ts": v.created, "meta": meta,
                       "thumb": C.thumbnail(str(v.path), v.created, 0.8)})
    return {"projects": projects, "videos": videos, "unreadable": unreadable}


def _sort(items: list[dict], how: str) -> list[dict]:
    if how == "Oldest first":
        return sorted(items, key=lambda x: x["ts"])
    if how == "Name A–Z":
        return sorted(items, key=lambda x: x["name"].lower())
    if how == "Name Z–A":
        return sorted(items, key=lambda x: x["name"].lower(), reverse=True)
    return sorted(items, key=lambda x: x["ts"], reverse=True)


# ------------------------------------------------------------------ dialogs
@st.dialog("Rename")
def rename_dialog(kind: str, target, current: str) -> None:
    name = st.text_input("Name", current, max_chars=120, key=f"rn_{kind}_{Path(target).name}")
    c1, c2 = st.columns(2)
    if c1.button("Save", type="primary", width="stretch", disabled=not name.strip()):
        try:
            if kind == "project":
                workspace.Project.rename_file(Path(target), name)
                cur = st.session_state.get("project")
                if cur is not None and cur.id == Path(target).stem:
                    cur.name = name.strip()
            else:
                library.rename_video(Path(target), name)
            st.session_state.pj_flash = "Renamed."
            st.rerun()
        except (OSError, ValueError) as e:
            st.error(str(e))
    if c2.button("Cancel", width="stretch"):
        st.rerun()


@st.dialog("Delete")
def delete_dialog(kind: str, target, title: str) -> None:
    if kind == "project":
        st.write(f"Delete project **{title}**?")
        st.caption("Only the project is removed. Imported media and rendered videos are kept.")
    else:
        st.write(f"Delete video **{title}**?")
        st.caption("The rendered file and its plan/EDL files are removed from the outputs folder. "
                   "This can't be undone.")
    c1, c2 = st.columns(2)
    if c1.button("Delete", type="primary", icon=":material/delete:", width="stretch"):
        try:
            if kind == "project":
                workspace.Project.delete_file(Path(target))
                cur = st.session_state.get("project")
                if cur is not None and cur.id == Path(target).stem:
                    st.session_state.pop("project", None)
                    st.session_state.new_project = True
            else:
                library.delete_video(Path(target))
            st.session_state.pj_flash = "Deleted."
            st.rerun()
        except (OSError, ValueError) as e:
            st.error(f"Couldn't delete: {e}")
    if c2.button("Cancel", width="stretch"):
        st.rerun()


@st.dialog("Details")
def details_dialog(kind: str, item: dict) -> None:
    if kind == "project":
        p = item["p"]
        rows = [("Name", p.name), ("Status", item["status"]), ("Clips", len(p.segments)),
                ("Sources", len(p.sources)), ("Length", C.fmt_dur(p.timeline_length())),
                ("Format", f"{p.export.get('aspect')} · {p.export.get('short_edge')}p"),
                ("Style", p.preset or "—"), ("Updated", _when(item["ts"]))]
        for s in p.sources:
            rows.append(("Source", Path(s).name + ("" if Path(s).exists() else "  (missing)")))
    else:
        v, m = item["v"], item["meta"]
        rows = [("Title", v.title), ("File", v.path.name), ("Created", _when(v.created)),
                ("Duration", C.fmt_dur(m["duration"])), ("Resolution", f"{m['w']}×{m['h']}"),
                ("Audio", "yes" if m["audio"] else "no"), ("Size", f"{v.path.stat().st_size / 1e6:.1f} MB"),
                ("Location", str(v.path.parent))]
    for k, val in rows:
        st.markdown(f"**{k}** &nbsp; {val}")


@st.dialog("Preview", width="large")
def preview_dialog(item: dict) -> None:
    v = item["v"]
    st.markdown(f"**{html.escape(v.title)}**")
    st.video(str(v.path))     # native controls: play/pause, seek, volume, fullscreen
    st.caption(f"{_when(v.created)} · {C.fmt_dur(item['meta']['duration'])} · "
               f"{item['meta']['w']}×{item['meta']['h']}")


def _open_project(p: workspace.Project) -> None:
    ss = st.session_state
    ss.project = p
    ss.sel = None
    ss.saved_version = p.version
    ss.pop("gen_report", None)
    state.go("workspace")


def _new_project() -> None:
    ss = st.session_state
    for k in ("project", "sel", "gen_report", "editor_export"):
        ss.pop(k, None)
    ss.new_project = True
    state.go("workspace")


# ------------------------------------------------------------------ pieces
def _section_header(icon: str, title: str, count: int, more: tuple[str, bool] | None) -> None:
    left, right = st.columns([8, 1.2], vertical_alignment="center")
    left.markdown(f'<div class="pj-sec"><span class="ic">{_svg(icon, 24)}</span><h2>{title}</h2>'
                  f'<span class="pj-count">{_plural(count, "project" if "Project" in title else "video")}'
                  f'</span></div>', unsafe_allow_html=True)
    if more is not None:
        key, expanded = more
        if right.button("Show less" if expanded else "View all →", key=f"more_{key}", type="tertiary"):
            st.session_state[f"pj_all_{key}"] = not expanded
            st.rerun()


def _empty(title: str, text: str, button: str | None = None, key: str = "", on_click=None,
           icon: str = ":material/add:") -> None:
    with st.container(key=f"pj_empty_{key}"):
        st.markdown(f'<div class="pj-empty"><div class="ic">{_svg("film", 30)}</div><h3>{title}</h3>'
                    f'<p>{text}</p></div>', unsafe_allow_html=True)
        if button:
            if st.button(button, type="primary", key=f"empty_btn_{key}", icon=icon):
                on_click()
                st.rerun()


def _project_card(it: dict) -> None:
    p, path = it["p"], it["path"]
    status = it["status"]
    cls = {"Draft": "draft", "In progress": "prog", "Completed": "done"}[status]
    with st.container(key=f"pj_card_{p.id}"):
        st.markdown(
            f'<div class="pj-thumb">{_img(it["cover"])}<span class="pj-badge {cls}"><i></i>{status}</span></div>'
            f'<div class="pj-title" title="{html.escape(p.name)}">{html.escape(p.name)}</div>'
            + _meta([("clips", _plural(len(p.segments), "clip")), ("link", _plural(len(p.sources), "source")),
                     ("clock", _when(it["ts"]))]), unsafe_allow_html=True)
        c1, c2 = st.columns([5, 1.1], vertical_alignment="center")
        if c1.button("Open in editor", key=f"open_{p.id}", type="primary", icon=":material/edit:", width="stretch"):
            _open_project(p)
            st.rerun()
        with c2.popover("", icon=":material/more_horiz:", width="stretch"):
            if st.button("Rename", key=f"rn_p_{p.id}", icon=":material/edit_note:", width="stretch"):
                rename_dialog("project", path, p.name)
            if st.button("Duplicate", key=f"dup_p_{p.id}", icon=":material/content_copy:", width="stretch"):
                try:
                    workspace.Project.duplicate_file(path)
                    st.session_state.pj_flash = "Project duplicated."
                    st.rerun()
                except (OSError, ValueError) as e:
                    st.error(str(e))
            if st.button("View details", key=f"dt_p_{p.id}", icon=":material/info:", width="stretch"):
                details_dialog("project", it)
            if st.button("Delete", key=f"del_p_{p.id}", icon=":material/delete:", width="stretch"):
                delete_dialog("project", path, p.name)


def _video_card(it: dict, n: int) -> None:
    v, m = it["v"], it["meta"]
    hd = "4K" if min(m["w"], m["h"]) >= 2160 else "HD" if min(m["w"], m["h"]) >= 720 else "SD"
    with st.container(key=f"pj_vid_{n}"):
        st.markdown(
            f'<div class="pj-thumb vid">{_img(it["thumb"])}<span class="pj-play">{_svg("play", 22)}</span>'
            f'<span class="pj-dur">{C.fmt_dur(m["duration"])}</span></div>'
            f'<div class="pj-title" title="{html.escape(v.title)}">{html.escape(v.title)}</div>'
            + _meta([("calendar", _when(v.created)), ("clock", C.fmt_dur(m["duration"])),
                     ("film", f"{hd}  {m['w']}×{m['h']}")]), unsafe_allow_html=True)
        # transparent button laid over the thumbnail: clicking the play overlay opens the preview
        if st.button("Preview video", key=f"pvbig_{n}"):
            preview_dialog(it)
        c = st.columns([1.1, 1.35, 1.0, 0.6], gap="small")
        if c[0].button("Preview", key=f"pv_{n}", icon=":material/play_arrow:", width="stretch"):
            preview_dialog(it)
        c[1].download_button("Download", v.path.read_bytes(), v.path.name, "video/mp4", key=f"dl_{n}",
                             icon=":material/download:", width="stretch")
        with c[2].popover("Share", icon=":material/share:", width="stretch"):
            st.caption("This video is stored on this computer, so there is no public link to copy. "
                       "Use Download to send the file, or copy its location:")
            st.code(str(v.path), language=None)
        with c[3].popover("", icon=":material/more_horiz:", width="stretch"):
            if st.button("Rename", key=f"rn_v_{n}", icon=":material/edit_note:", width="stretch"):
                rename_dialog("video", v.path, v.title)
            if st.button("View details", key=f"dt_v_{n}", icon=":material/info:", width="stretch"):
                details_dialog("video", it)
            if st.button("Delete", key=f"del_v_{n}", icon=":material/delete:", width="stretch"):
                delete_dialog("video", v.path, v.title)


def _grid(items: list, draw) -> None:
    for r in range(0, len(items), PER_ROW):
        cols = st.columns(PER_ROW, gap="medium")
        for col, (i, it) in zip(cols, list(enumerate(items))[r:r + PER_ROW]):
            with col:
                draw(it, i) if draw is _video_card else draw(it)


# ------------------------------------------------------------------ page
def render() -> None:
    ss = st.session_state
    navbar.render("projects")
    with st.container(key="pj_page"):
        st.markdown(
            '<div class="pj-head"><div><h1>My Projects</h1><p>Every video you\'ve generated.</p></div>'
            '<div class="pj-deco" aria-hidden="true"><svg width="120" height="110" viewBox="0 0 120 110" fill="none">'
            '<rect x="14" y="40" width="86" height="56" rx="10" fill="#17233b" stroke="#2d4a85" stroke-width="2"/>'
            '<path d="M14 40 28 14h22L36 40M46 40 60 14h22L68 40M78 40 92 14h12L100 40" fill="#22407d" '
            'stroke="#3b6de0" stroke-width="2"/><path d="M52 58v24l22-12z" fill="#5aa0ff"/></svg></div></div>',
            unsafe_allow_html=True)

        if flash := ss.pop("pj_flash", None):
            st.toast(flash, icon="✅")

        with st.container(key="pj_toolbar"):
            c = st.columns([4.6, 2.3, 2.3, 1.7], vertical_alignment="center", gap="small")
            q = c[0].text_input("Search", key="pj_q", placeholder="Search projects and videos...",
                                label_visibility="collapsed")
            flt = c[1].selectbox("Filter", FILTERS, key="pj_filter", label_visibility="collapsed",
                                 format_func=lambda x: f"Filter  |  {x}")
            srt = c[2].selectbox("Sort by", SORTS, key="pj_sort", label_visibility="collapsed",
                                 format_func=lambda x: f"Sort by  |  {x}")
            if c[3].button("New Project", type="primary", icon=":material/add:", width="stretch", key="pj_new"):
                _new_project()
                st.rerun()

        sk = st.empty()
        sk.markdown('<div class="pj-skel">' + '<div></div>' * 3 + '</div>', unsafe_allow_html=True)
        try:
            data = gather()
        except Exception as e:  # unexpected I/O problem: show it with a retry instead of a broken page
            sk.empty()
            st.error(f"Couldn't load your projects: {e}")
            if st.button("Retry", icon=":material/refresh:", key="pj_retry"):
                st.rerun()
            return
        sk.empty()
        if data["unreadable"]:
            st.warning(f"{data['unreadable']} project file(s) couldn't be read and are hidden.")

        needle = q.strip().lower()
        projects = [x for x in data["projects"] if needle in x["name"].lower()]
        if flt != "All projects":
            projects = [x for x in projects if x["status"] == flt]
        videos = [x for x in data["videos"] if needle in x["name"].lower()]
        projects, videos = _sort(projects, srt), _sort(videos, srt)
        searching = bool(needle) or flt != "All projects"

        def reset() -> None:
            ss.pj_q, ss.pj_filter = "", "All projects"

        # ---- Editor projects
        all_p = ss.get("pj_all_projects", False)
        _section_header("folder", "Editor Projects", len(projects),
                        ("projects", all_p) if len(projects) > PER_ROW else None)
        if projects:
            _grid(projects if all_p else projects[:PER_ROW], _project_card)
        elif searching and data["projects"]:
            _empty("No matching projects found.", "Try a different search or clear the filter.",
                   "Clear search and filter", "nomatch_p", reset)
        else:
            _empty("No projects yet", "Create your first video editing project.", "New Project", "p", _new_project)

        st.markdown('<hr class="pj-hr">', unsafe_allow_html=True)

        # ---- Rendered videos
        all_v = ss.get("pj_all_videos", False)
        _section_header("playc", "Rendered Videos", len(videos), ("videos", all_v) if len(videos) > PER_ROW else None)
        if videos:
            _grid(videos if all_v else videos[:PER_ROW], _video_card)
        elif needle and data["videos"]:
            _empty("No matching videos found.", "Try a different search.", "Clear search and filter",
                   "nomatch_v", reset)
        else:
            _empty("No rendered videos yet", "Your exported videos will appear here.", "Go to Workspace", "v",
                   lambda: state.go("workspace"), icon=":material/movie_edit:")
