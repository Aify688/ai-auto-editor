"""Advanced editing: explicit skill selection (Custom) and natural-language edits (Chat).

Same registry, validator and engine as the preset flow; kept for users who want control.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from video_editor import planning, registry, validate
from video_editor.engine import execute_plan
from video_editor.ffmpeg_ops import FFmpegError
from video_editor.validate import PlanError

from . import state


def plan_panel(plan: dict, key: str) -> None:
    v = validate.validate_plan(plan)
    c1, c2, c3 = st.columns(3)
    c1.metric("Segments", len(v.plan.get("segments", [])))
    c2.metric("Length", f"{v.plan.get('_estimated_duration', 0):.1f}s")
    e = v.plan.get("export", {})
    c3.metric("Export", f"{e.get('aspect')} · {e.get('short_edge')}p")
    for line in plan.get("rationale", []):
        st.write("• " + line)
    for w in v.warnings:
        st.warning(w)
    for err in v.errors:
        st.error(err)
    if v.ok:
        for note in validate.review_plan(v.plan, v.clips):
            st.info(note)
    with st.expander("Segments"):
        st.table([{"clip": s["clip"], "start": s["start"], "end": s["end"]} for s in v.plan.get("segments", [])])
    with st.expander("Plan JSON"):
        st.code(json.dumps(plan, indent=2), language="json")
    if st.button("Render this plan", type="primary", disabled=not v.ok, key=f"adv_render_{key}",
                 icon=":material/play_arrow:"):
        bar = st.progress(0.0)
        try:
            res = execute_plan(plan, lambda f, m: bar.progress(min(max(f, 0.0), 1.0), text=m))
            st.session_state[f"adv_result_{key}"] = res
        except (PlanError, FFmpegError, ValueError) as ex:
            st.error(f"Render failed: {ex}")
    res = st.session_state.get(f"adv_result_{key}")
    if res is not None and Path(res.output).exists():
        st.video(str(res.output))
        st.download_button("Download MP4", Path(res.output).read_bytes(), Path(res.output).name, "video/mp4",
                           key=f"adv_dl_{key}", icon=":material/download:")


def custom_tab(paths: list[Path], caption_files: dict) -> None:
    chosen: dict[str, dict] = {}
    by_cat: dict[str, list] = {}
    for c in registry.CAPS:
        if c.kind == "feature" and c.stage in ("analyze", "segment", "join", "master", "overlay"):
            by_cat.setdefault(c.category, []).append(c)
    for cat, caps in by_cat.items():
        avail = [c for c in caps if c.available and c.id != "captions.import"]
        if not avail:
            continue
        with st.expander(cat):
            for c in avail:
                if c.id == "captions.burn" and not caption_files and not registry.get("captions.transcribe").available:
                    st.checkbox(f"{c.name} — needs an SRT/VTT upload", disabled=True, key=f"u_{c.id}")
                    continue
                if st.checkbox(f"**{c.name}** — {c.description}", key=f"on_{c.id}"):
                    vals = {}
                    for s in c.settings:
                        k = f"set_{c.id}_{s.name}"
                        if s.type == "float":
                            vals[s.name] = st.number_input(
                                s.name, float(s.min if s.min is not None else -1e6),
                                float(s.max if s.max is not None else 1e6),
                                float(s.default if s.default is not None else 0.0), step=0.05, key=k)
                        elif s.type == "int":
                            vals[s.name] = st.number_input(s.name, int(s.min), int(s.max), int(s.default), key=k)
                        elif s.type == "bool":
                            vals[s.name] = st.checkbox(s.name, bool(s.default), key=k)
                        elif s.type == "choice":
                            vals[s.name] = st.selectbox(s.name, list(s.choices), list(s.choices).index(s.default),
                                                        key=k)
                        elif s.type == "text":
                            vals[s.name] = st.text_input(s.name, s.default or "", key=k)
                        elif s.type == "file":
                            up = st.file_uploader(s.name, key=k)
                            if up is not None:
                                vals[s.name] = str(state.save_upload(up, "assets"))
                    chosen[c.id] = vals
    x1, x2, x3, x4 = st.columns(4)
    aspect = x1.selectbox("Aspect", list(validate.ASPECTS) + ["match_first"], key="cu_aspect")
    fit = x2.selectbox("Fit", list(validate.FITS), key="cu_fit")
    short = x3.selectbox("Resolution", [720, 1080, 1440], index=1, key="cu_short")
    fps = x4.selectbox("FPS", [24, 25, 30, 60], index=2, key="cu_fps")
    crf = st.slider("Quality (CRF, lower = better)", 14, 30, 20, key="cu_crf")
    if st.button("Build plan", key="custom_build", icon=":material/construction:"):
        missing = [k for k, v in chosen.items() for s in registry.get(k).settings if s.required and not v.get(s.name)]
        if missing:
            st.error("Required settings missing for: " + ", ".join(sorted(set(missing))))
        else:
            sel = planning.Selection(skills=chosen, caption_files=caption_files,
                                     export={"aspect": aspect, "fit": fit, "short_edge": short, "fps": fps, "crf": crf})
            try:
                st.session_state.custom_plan = planning.build_plan(paths, sel, "", "custom")
            except (FFmpegError, ValueError) as ex:
                st.error(str(ex))
    if "custom_plan" in st.session_state:
        plan_panel(st.session_state.custom_plan, "custom")


def chat_tab(paths: list[Path], caption_files: dict, sig) -> None:
    if st.session_state.get("chat_sig") != (sig, tuple(caption_files)):
        st.session_state.chat = planning.ChatSession(paths, caption_files) if paths else None
        st.session_state.chat_sig = (sig, tuple(caption_files))
    chat = st.session_state.chat
    if chat is None:
        st.info("Upload a video first.")
        return
    for turn in chat.history:
        with st.chat_message("user"):
            st.write(turn.user)
        with st.chat_message("assistant"):
            st.write(turn.reply)
    msg = st.chat_input("e.g. remove pauses, make it vertical, warm look")
    if msg:
        try:
            chat.send(msg)
            st.rerun()
        except (FFmpegError, ValueError) as ex:
            st.error(str(ex))
    if chat.plan:
        if st.button("Undo last message", icon=":material/undo:"):
            chat.undo()
            st.rerun()
        plan_panel(chat.plan, "chat")
