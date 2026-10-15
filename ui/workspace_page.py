"""Unified editing workspace: top bar · tool rail · media/tools · preview · AI panel · full-width timeline.

Replaces the separate Create Video and Editor pages. Generate AI Video runs the preset
pipeline and loads the result onto the timeline for review; Export renders the timeline.
"""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from video_editor import analysis, ffmpeg_ops, presets, registry, validate, workspace
from video_editor.validate import PlanError

from . import advanced, editor, state, theme
from . import components as C

RAIL = [("media", "perm_media", "Media"), ("ai", "auto_awesome", "AI Edit"), ("audio", "music_note", "Audio"),
        ("text", "title", "Text"), ("captions", "closed_caption", "Captions"), ("effects", "auto_fix_high", "Effects"),
        ("templates", "dashboard_customize", "Templates")]
ASPECTS = ["16:9", "9:16", "1:1", "4:5"]
LOOKS = ["warm", "cool", "cinematic", "vivid", "bw", "faded"]


# ------------------------------------------------------------------ left content panels
def _panel_title(text: str, sub: str = "") -> None:
    st.markdown(f"<div class='ws-h'>{html.escape(text)}</div>"
                + (f"<div class='ws-sub'>{html.escape(sub)}</div>" if sub else ""), unsafe_allow_html=True)


def panel_media(P, ms) -> None:
    _panel_title("Your Media", "Manage files for your project.")
    editor._tool_media(P, ms)


def panel_ai(P, ms) -> None:
    _panel_title("AI Edit", "What the AI did, and what it can't do.")
    if P.notes:
        for n in P.notes:
            st.caption("• " + n)
    else:
        st.caption("Pick a style on the right and press Generate AI Video.")
    st.divider()
    editor._tool_ai(P, ms)
    paths = [Path(p) for p in P.sources if Path(p).exists()]
    if paths:
        caption_files = _srt_from_cues(P.cues)
        with st.expander("Advanced: pick skills yourself"):
            advanced.custom_tab(paths, caption_files)
        with st.expander("Advanced: ask in plain language"):
            sig = tuple((p.name, p.stat().st_size) for p in paths)
            advanced.chat_tab(paths, caption_files, sig)


def panel_audio(P, ms) -> None:
    _panel_title("Audio")
    editor._tool_audio(P, ms)
    st.markdown("##### Levels")
    editor.toggle_skill(P, "audio.clean", "Clean voice (denoise)")
    if editor.toggle_skill(P, "audio.loudnorm", "Normalize loudness"):
        editor.slider_skill(P, "audio.loudnorm", "target_lufs", "Target (LUFS)", -14.0, -24.0, -9.0, 0.5)
    if editor.toggle_skill(P, "audio.volume", "Voice gain"):
        editor.slider_skill(P, "audio.volume", "gain_db", "Gain (dB)", 0.0, -20.0, 12.0, 0.5)
    if editor.toggle_skill(P, "audio.fades", "Fades"):
        editor.slider_skill(P, "audio.fades", "fade_in", "In (s)", 0.3, 0.0, 5.0, 0.1)
        editor.slider_skill(P, "audio.fades", "fade_out", "Out (s)", 0.8, 0.0, 5.0, 0.1)


def panel_text(P, ms) -> None:
    _panel_title("Text")
    editor.text_controls(P, ms)
    st.markdown("##### Logo overlay")
    editor._tool_stickers(P, ms)


def panel_captions(P, ms) -> None:
    _panel_title("Captions")
    editor.subtitle_controls(P, ms)
    if P.cues:
        st.markdown("##### Lines")
        for c in sorted(P.cues, key=lambda c: (c["clip"], c["start"]))[:60]:
            col1, col2 = st.columns([5, 1], vertical_alignment="center")
            new = col1.text_input(f"{editor._fmt(c['start'])}", c["text"], key=editor._k(P, "cap", c["id"]))
            if new.strip() and new.strip() != c["text"]:
                P.update_cue_text(c["id"], new)
            if col2.button("", icon=":material/delete:", key=f"capdel_{c['id']}", help="Delete line"):
                P.set_cues([x for x in P.cues if x["id"] != c["id"]])
                st.rerun()


def panel_effects(P, ms) -> None:
    _panel_title("Effects")
    with st.expander("Filters & color", expanded=True):
        editor._tool_filters(P, ms)
    with st.expander("Transitions"):
        editor._tool_transitions(P, ms)
    with st.expander("Video effects"):
        editor._tool_effects(P, ms)


def panel_templates(P, ms) -> None:
    _panel_title("Templates", "One-click style bundles.")
    for key, p in presets.PRESETS.items():
        with st.container(border=True):
            st.markdown(f":material/{p.icon}: **{p.name}** · {p.aspect}")
            st.caption(p.tagline)
            if st.button("Use template", key=f"tpl_{key}", width="stretch"):
                apply_preset(P, key)
                st.session_state.right_tab = "AI Edit"
                st.rerun()


PANELS = {"media": panel_media, "ai": panel_ai, "audio": panel_audio, "text": panel_text,
          "captions": panel_captions, "effects": panel_effects, "templates": panel_templates}


# ------------------------------------------------------------------ right: AI Auto Edit
def apply_preset(P, key: str) -> None:
    ss = st.session_state
    p = presets.PRESETS[key]
    ss.preset = key
    for sw, val in p.switches.items():
        ss[f"ai_sw_{sw}"] = val
    ss["ai_hook"] = p.hook
    ss["ai_target"] = p.target
    P.set_export(aspect=p.aspect)


def _srt_from_cues(cues: list[dict]) -> dict[int, str]:
    out: dict[int, list] = {}
    for c in cues:
        out.setdefault(c["clip"], []).append(c)

    def ts(x: float) -> str:
        h, rem = divmod(int(x * 1000), 3600000)
        m, rem = divmod(rem, 60000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    res = {}
    for clip, lst in out.items():
        res[clip] = "\n\n".join(f"{i}\n{ts(c['start'])} --> {ts(c['end'])}\n{c['text']}"
                                for i, c in enumerate(sorted(lst, key=lambda c: c["start"]), 1))
    return res


def ai_panel(P, ms) -> None:
    ss = st.session_state
    st.markdown("<div class='ws-h'>✦ AI Auto Edit</div><div class='ws-sub'>Generate a polished video in one click.</div>",
                unsafe_allow_html=True)
    C.label("Editing style")
    theme.selected_card_css([ss.preset])
    for key, p in presets.PRESETS.items():
        with st.container(key=f"card_{key}"):
            c1, c2 = st.columns([1.2, 1.6], vertical_alignment="center")
            if c1.button(p.name, key=f"style_{key}", icon=f":material/{p.icon}:", width="stretch",
                         type="primary" if ss.preset == key else "secondary"):
                apply_preset(P, key)
                st.rerun()
            c2.markdown(f"<span class='ws-sub' style='margin:0'>{html.escape(p.tagline)}</span>", unsafe_allow_html=True)

    C.label("Output format")
    cur = P.export["aspect"] if P.export["aspect"] in ASPECTS else "16:9"
    asp = st.radio("Output format", ASPECTS, index=ASPECTS.index(cur), key=editor._k(P, "ai_asp"),
                   horizontal=True, label_visibility="collapsed")
    if asp != P.export["aspect"]:
        P.set_export(aspect=asp)
        st.rerun()

    C.label("AI tools")
    has_srt = bool(P.cues)
    sw = {}
    for key in presets.SWITCHES:
        icon, name, tip = presets.SWITCH_INFO[key]
        disabled, why = False, tip
        if key == "subtitles":
            ok, why = presets.subtitle_source_available(has_srt)
            if not ok:
                disabled, ss["ai_sw_subtitles"] = True, False
        sw[key] = st.toggle(f":material/{icon}: {name}", key=f"ai_sw_{key}", help=why, disabled=disabled)
        if key == "autocut" and sw[key]:
            total = sum(m["duration"] for m in ms) or 6.0
            hi = float(max(6, int(total)))
            ss.setdefault("ai_target", min(presets.PRESETS[ss.preset].target, hi))
            ss["ai_target"] = min(max(5.0, float(ss["ai_target"])), hi)
            st.slider("Target length (s)", 5.0, hi, key="ai_target", step=1.0)
        if key == "music" and sw[key]:
            mf = st.file_uploader("Music file", type=["mp3", "wav", "m4a", "aac"], key="ai_music_up",
                                  label_visibility="collapsed")
            if mf is not None:
                ss["ai_music_path"] = str(state.save_upload(mf, "assets"))
    music_path = ss.get("ai_music_path") if sw.get("music") else None

    with st.expander("Advanced settings"):
        ss.setdefault("ai_hook", presets.PRESETS[ss.preset].hook)
        st.toggle("Open with strongest moment (hook)", key="ai_hook",
                  help="Moves the highest-scoring moment to the start when Auto cut selects moments.")
        look = st.selectbox("Look", ["Style default"] + LOOKS, key="ai_look")
        c1, c2 = st.columns(2)
        fit = c1.selectbox("Fit", list(validate.FITS), index=list(validate.FITS).index(P.export["fit"]),
                           format_func={"crop": "Fill", "blur": "Blur bars", "pad": "Letterbox"}.get, key=editor._k(P, "ai_fit"))
        res = c2.selectbox("Resolution", [720, 1080, 1440], key=editor._k(P, "ai_res"),
                           index=[720, 1080, 1440].index(P.export["short_edge"]) if P.export["short_edge"] in (720, 1080, 1440) else 1)
        if (fit, res) != (P.export["fit"], P.export["short_edge"]):
            P.set_export(fit=fit, short_edge=res)
            st.rerun()

    problems = []
    if not ms:
        problems.append("Import a video in Media first.")
    if sw.get("music") and not music_path:
        problems.append("Add a music file or switch music off.")
    for pr in problems:
        st.caption(f":material/info: {pr}")
    label = "Regenerate AI Video" if P.segments and P.preset else "Generate AI Video"
    with st.container(key="gen_bar"):
        go = st.button(label, type="primary", icon=":material/auto_awesome:", width="stretch", key="generate",
                       disabled=bool(problems))
    if go:
        _run_generation(P, ms, sw, music_path, None if look == "Style default" else look)

    rep = ss.get("gen_report")
    if rep:
        for u in rep["unsupported"]:
            st.warning(u)
        with st.expander(f"Edit decisions ({len(rep['notes'])})"):
            for n in rep["notes"]:
                st.caption("• " + n)


def _run_generation(P, ms, sw, music_path, look) -> None:
    ss = st.session_state
    steps = workspace.generation_steps(sw)
    keys = [k for k, _ in steps]
    box = st.container(border=True)
    with box:
        bar = st.progress(0.0)
        ph = st.empty()

    def show(active: str, frac: float) -> None:
        bar.progress(min(max(frac, 0.0), 1.0))
        ph.markdown(C.steps_list([(k, label, "") for k, label in steps], active, done_all=active == "done"),
                    unsafe_allow_html=True)

    def on_event(key: str) -> None:
        i = keys.index(key) if key in keys else 0
        show(key, (i + 0.5) / (len(keys) + 0.5))

    caption_files = _srt_from_cues(P.cues) if (sw.get("subtitles") and P.cues) else None
    show("analyze", 0.02)
    try:
        rep = workspace.generate_from_preset(
            P, ss.preset, sw, target=ss.get("ai_target") if sw.get("autocut") else None, hook=ss.get("ai_hook"),
            caption_files=caption_files, music_path=music_path, look=look,
            whisper_model=ss.settings["whisper_model"], progress=on_event)
    except (PlanError, ffmpeg_ops.FFmpegError, ValueError) as ex:
        st.error(f"Could not generate: {ex}")
        return
    show("done", 1.0)
    ss.gen_report = rep
    ss.sel = None          # (right_tab already shows AI Edit: generation can only be started from that tab)
    st.rerun()


# ------------------------------------------------------------------ top bar
def top_bar(P) -> None:
    ss = st.session_state
    c = st.columns([1.5, 2.6, 1.2, 3.0, 0.45, 0.45, 0.45, 0.45, 0.45, 1.2], vertical_alignment="center")
    c[0].markdown("<div class='ws-brand'><i></i>FrameFlow</div>", unsafe_allow_html=True)
    new = c[1].text_input("Project name", P.name, label_visibility="collapsed", key=f"pname_{P.id}")
    if new.strip() and new != P.name:
        P.name = new.strip()
        P.version += 1
    dirty = P.version != ss.get("saved_version", -1) and bool(P.sources)
    c[2].markdown(f"<span class='ws-status'>{'● Saving…' if dirty else '✓ Saved'}</span>", unsafe_allow_html=True)
    c[4].button("", icon=":material/undo:", help="Undo", disabled=not P.can_undo, key="undo", on_click=P.undo,
                width="stretch")
    c[5].button("", icon=":material/redo:", help="Redo", disabled=not P.can_redo, key="redo", on_click=P.redo,
                width="stretch")
    c[6].button("", icon=":material/left_panel_close:" if ss.get("left_open", True) else ":material/left_panel_open:",
                help="Toggle media panel", key="tg_left", width="stretch",
                on_click=lambda: ss.__setitem__("left_open", not ss.get("left_open", True)))
    c[7].button("", icon=":material/right_panel_close:" if ss.get("right_open", True) else ":material/right_panel_open:",
                help="Toggle AI panel", key="tg_right", width="stretch",
                on_click=lambda: ss.__setitem__("right_open", not ss.get("right_open", True)))
    with c[8].popover("", icon=":material/menu:", help="Menu", width="stretch"):
        for page, label, icon in [("dashboard", "Dashboard", ":material/dashboard:"),
                                  ("projects", "My Projects", ":material/folder:"),
                                  ("settings", "Settings", ":material/settings:")]:
            if st.button(label, icon=icon, key=f"menu_{page}", width="stretch"):
                state.go(page)
                st.rerun()
        if st.button("New project", icon=":material/add:", key="menu_new", width="stretch"):
            for k in ("project", "sel", "gen_report", "editor_export"):
                ss.pop(k, None)
            ss.new_project = True
            st.rerun()
    if c[9].button("Export", type="primary", icon=":material/download:", key="export_btn", width="stretch",
                   disabled=not P.segments):
        editor.export_dialog(P)


# ------------------------------------------------------------------ page
def render() -> None:
    ss = st.session_state
    P = editor.project()
    ms = editor.metas(P)
    ss.setdefault("tool", "media")
    ss.setdefault("right_tab", "AI Edit")
    ss.setdefault("left_open", True)
    ss.setdefault("right_open", True)
    if "preset" not in ss or ss.preset not in presets.PRESETS:
        ss.preset = ss.settings.get("default_preset", "dynamic")
    if ss.get("last_preset_applied") != ss.preset:
        for sw_, val in presets.PRESETS[ss.preset].switches.items():
            ss.setdefault(f"ai_sw_{sw_}", val)
        ss.last_preset_applied = ss.preset
    theme.workspace_css()

    root = st.container(key="ws_root")
    with root:
        top = st.container(key="ws_top")
        body = st.container(key="ws_body")
        tl = st.container(key="ws_timeline")

    with body:
        spec = [0.62] + ([2.5] if ss.left_open else []) + [6.0] + ([2.8] if ss.right_open else [])
        cols = st.columns(spec, gap="small")
    it = iter(cols)
    rail = next(it)
    left = next(it) if ss.left_open else None
    center = next(it)
    right = next(it) if ss.right_open else None

    sel = ss.get("sel")
    with center:
        with st.container(key="ws_preview"):
            v_prev = editor._component(**editor._args(P, ms, sel, "preview"), key="ws_prev", default=None)
    with tl:
        v_tl = editor._component(**editor._args(P, ms, sel, "timeline"), key="ws_tl", default=None)
    editor._process(P, ms, v_prev)
    editor._process(P, ms, v_tl)

    with rail:
        with st.container(key="ws_rail"):
            for key, icon, label in RAIL:
                if st.button(label, icon=f":material/{icon}:", key=f"rail_{key}", width="stretch",
                             type="primary" if ss.tool == key else "tertiary"):
                    ss.tool = key
                    if key == "ai":
                        ss.right_open = True
                        ss.right_tab = "AI Edit"
                    st.rerun()
    if left is not None:
        with left:
            with st.container(key="ws_left"):
                PANELS[ss.tool](P, ms)
    if right is not None:
        with right:
            with st.container(key="ws_right"):
                tab = st.radio("Right panel", ["AI Edit", "Properties"], key="right_tab", horizontal=True,
                               label_visibility="collapsed")
                if tab == "AI Edit":
                    ai_panel(P, ms)
                else:
                    editor.right_panel(P, ms)

    if P.sources and P.version != ss.get("saved_version"):
        P.save()
        ss.saved_version = P.version
    with top:
        top_bar(P)
