"""CapCut-style editor workspace: toolbar, tools, preview + timeline, properties.

Preview/timeline is a custom component (ui/timeline_component). Everything else is
native Streamlit bound to video_editor.workspace.Project, which becomes the same
plan the engine validates and renders.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from video_editor import analysis, ffmpeg_ops, media, registry, validate, workspace
from video_editor.engine import execute_plan
from video_editor.validate import PlanError

from . import state

_component = components.declare_component(
    "ave_editor", path=str(Path(__file__).parent / "timeline_component"))

LOOKS = ["warm", "cool", "cinematic", "vivid", "bw", "faded"]
TRANSITIONS = ["fade", "fadeblack", "fadewhite", "dissolve", "wipeleft", "wiperight", "slideleft", "slideright",
               "circleopen", "pixelize"]
EFFECT_PREFIXES = ("color.", "fx.", "time.", "graphics.", "audio.clean", "audio.loudnorm")


# ------------------------------------------------------------------ project / media
def project() -> workspace.Project:
    """Current project; on first load, reopen the most recently saved one (unless New project was chosen)."""
    ss = st.session_state
    if "project" not in ss:
        saved = [] if ss.pop("new_project", False) else workspace.Project.list_saved()
        loaded = None
        for path in saved[:1]:
            try:
                loaded = workspace.Project.load(path)
            except (OSError, ValueError, KeyError):
                loaded = None
        ss.project = loaded or workspace.Project()
        ss.sel = None
        ss.saved_version = ss.project.version
    return ss.project


@st.cache_data(show_spinner="Preparing preview…", max_entries=64)
def _ingest(path: str, mtime: float) -> dict:
    return media.ingest(Path(path))


def metas(P: workspace.Project) -> list[dict]:
    out = []
    for p in P.sources:
        pp = Path(p)
        out.append(_ingest(p, pp.stat().st_mtime) if pp.exists() else
                   {"id": "missing", "name": pp.name + " (missing)", "duration": 0, "proxy_url": "", "sprite_url": "",
                    "sprite": {"step": 1, "count": 1, "tile_w": 96, "tile_h": 54}, "peaks": [], "peak_step": 0.1,
                    "w": 0, "h": 0, "has_audio": False, "path": p})
    return out


def _import(P: workspace.Project, files) -> None:
    for f in files:
        tmp = state.save_upload(f, "editor_in")
        dest = media.import_file(tmp, f.name)
        i = P.add_source(dest)
        m = _ingest(str(dest), dest.stat().st_mtime)
        if not any(s["clip"] == i for s in P.segments):
            P.append_clip(i, m["duration"])


def _fmt(s: float) -> str:
    m = int(s // 60)
    return f"{m}:{s - 60 * m:04.1f}"


# ------------------------------------------------------------------ component bridge
def _args(P, ms, sel, mode: str = "preview") -> dict:
    effects = []
    for sid in P.skills:
        if sid.startswith(EFFECT_PREFIXES) and sid in registry.REGISTRY:
            effects.append({"id": sid, "label": registry.get(sid).name})
    tr = P.skills.get("transition.crossfade")
    mus = P.skills.get("audio.music_bed")
    music = None
    if mus and mus.get("path") and Path(mus["path"]).exists():
        music = {"url": media.audio_preview_url(Path(mus["path"])), "volume": mus.get("volume", 0.3),
                 "name": Path(mus["path"]).name}
    keep = ("id", "name", "duration", "w", "h", "has_audio", "proxy_url", "sprite_url", "sprite", "peaks", "peak_step")
    return {"mode": mode, "short_edge": P.export.get("short_edge", 1080), "version": P.version, "sources": [{k: m[k] for k in keep} for m in ms],
            "segments": P.segments, "cues": P.cues, "speed": P.speed(), "aspect": P.export["aspect"],
            "fit": P.export["fit"], "music": music, "effects": effects,
            "transition": {"type": tr["type"], "duration": tr["duration"]} if tr else None,
            "captions": "captions.burn" in P.skills and bool(P.cues), "selection": sel,
            "sig": f"{P.export['aspect']}|{P.export['fit']}|{P.speed()}|{','.join(P.skills)}|{len(P.cues)}",
            "height": 700}


def _process(P, ms, value) -> None:
    ss = st.session_state
    if not value:
        return
    seen = ss.setdefault("last_seq_by", {})
    src = value.get("src", "x")
    if value.get("seq", 0) == seen.get(src):
        return
    seen[src] = value["seq"]
    ss.playhead = value.get("playhead", 0.0)
    kind = value.get("kind")
    durs = {i: m["duration"] for i, m in enumerate(ms)}
    if kind == "select":
        ss.sel = value.get("selection")
        if ss.sel:
            ss.right_tab = "Properties"
    elif kind == "segments":
        problems = P.set_segments(value["segments"], durs)
        if problems:
            st.toast("Edit rejected: " + "; ".join(sorted(set(problems))), icon="⚠️")
        ss.sel = value.get("selection")
        if ss.sel:
            ss.right_tab = "Properties"
    elif kind == "cues":
        P.set_cues(value["cues"])
        ss.sel = None
    elif kind == "export":
        P.set_export(aspect=value["aspect"])


# ------------------------------------------------------------------ widgets bound to skills
def _k(P, *parts) -> str:
    return "_".join(str(p) for p in (*parts, P.version))


def slider_skill(P, sid: str, name: str, label: str, default: float, lo: float, hi: float, step: float,
                 base: dict | None = None) -> None:
    cur = P.skills.get(sid, base or {})
    val = st.slider(label, lo, hi, float(cur.get(name, default)), step, key=_k(P, "sl", sid, name))
    if val != cur.get(name, default) or (sid not in P.skills and val != default):
        P.set_skill(sid, {**(cur or {}), name: val})


def toggle_skill(P, sid: str, label: str, settings: dict | None = None, help: str | None = None) -> bool:
    on = st.toggle(label, value=sid in P.skills, key=_k(P, "tg", sid), help=help)
    if on and sid not in P.skills:
        cap = registry.get(sid)
        defaults, _ = cap.normalize_settings(settings or {s.name: s.default for s in cap.settings if not s.required})
        P.set_skill(sid, settings or {k: v for k, v in defaults.items() if v is not None})
    elif not on and sid in P.skills:
        P.set_skill(sid, None)
    return on


def _scope(text: str) -> None:
    st.caption(f":material/layers: {text}")


@st.dialog("Export", width="large")
def export_dialog(P) -> None:
    ss = st.session_state
    plan = P.to_plan()
    v = validate.validate_plan(plan)
    c1, c2, c3 = st.columns(3)
    c1.metric("Length", f"{v.plan.get('_estimated_duration', 0):.1f}s")
    c2.metric("Format", f"{P.export['aspect']} · {P.export['short_edge']}p")
    c3.metric("Clips", len(P.segments))
    for e in v.errors:
        st.error(e)
    for w in v.warnings:
        st.warning(w)
    if st.button("Render", type="primary", disabled=not v.ok, key="do_render", width="stretch",
                 icon=":material/movie:"):
        bar = st.progress(0.0, text="Starting…")
        try:
            res = execute_plan(plan, lambda f, m: bar.progress(min(max(f, 0), 1), text=m))
            ss.editor_export = {"output": str(res.output), "plan": str(res.plan_path), "edl": str(res.edl_path)}
        except (PlanError, ffmpeg_ops.FFmpegError, ValueError) as ex:
            st.error(f"Render failed: {ex}")
    r = ss.get("editor_export")
    if r and Path(r["output"]).exists():
        orig = next((p for p in P.sources if Path(p).exists()), None)
        view = st.segmented_control("Compare", ["After", "Before", "Side by side"], default="After",
                                    key="ex_cmp", label_visibility="collapsed") or "After"
        if view == "Before" and orig:
            st.video(orig)
        elif view == "Side by side" and orig:
            ca, cb = st.columns(2)
            ca.caption("Before (first source clip)")
            ca.video(orig)
            cb.caption("After")
            cb.video(r["output"])
        else:
            st.video(r["output"])
        a, b, c = st.columns(3)
        a.download_button("MP4", Path(r["output"]).read_bytes(), Path(r["output"]).name, "video/mp4",
                          type="primary", width="stretch", key="ex_mp4")
        b.download_button("Plan", Path(r["plan"]).read_bytes(), Path(r["plan"]).name, "application/json",
                          width="stretch", key="ex_plan")
        c.download_button("EDL", Path(r["edl"]).read_bytes(), Path(r["edl"]).name, "text/plain",
                          width="stretch", key="ex_edl")


# ------------------------------------------------------------------ tool panels (used by ui/workspace_page.py)
def _tool_media(P, ms) -> None:
    files = st.file_uploader("Import videos", type=["mp4", "mov"], accept_multiple_files=True, key="imp",
                             label_visibility="collapsed")
    if files:
        sig = tuple((f.name, f.size) for f in files)
        if st.session_state.get("imp_sig") != sig:
            st.session_state.imp_sig = sig
            with st.spinner("Importing…"):
                _import(P, files)
            st.rerun()
    for i, m in enumerate(ms):
        with st.container(border=True):
            if m.get("id") != "missing":
                from . import components as C
                C.thumb(Path(m["path"]))
            st.markdown(f"**{m['name']}**")
            st.caption(f"{_fmt(m['duration'])} · {m['w']}×{m['h']}")
            if st.button("Add to timeline", key=f"add_{i}", icon=":material/add:", width="stretch",
                         disabled=m.get("id") == "missing"):
                P.append_clip(i, m["duration"])
                st.rerun()
    if not ms:
        st.caption("Import a video to begin.")


def _tool_audio(P, ms) -> None:
    mus = P.skills.get("audio.music_bed")
    mf = st.file_uploader("Add music", type=["mp3", "wav", "m4a", "aac"], key="mus_up", label_visibility="collapsed")
    if mf is not None:
        path = str(state.save_upload(mf, "assets"))
        if not mus or mus.get("path") != path:
            P.set_skill("audio.music_bed", {"path": path, "volume": 0.25, "duck": True})
            st.rerun()
    if mus:
        st.caption(f":material/music_note: {Path(mus['path']).name}")
        if st.button("Remove music", key="mus_rm", icon=":material/delete:", width="stretch"):
            P.set_skill("audio.music_bed", None)
            st.rerun()
    else:
        st.caption("No music. Upload a file to mix under your dialogue.")
    reason = registry.get("ext.generative_video").status()[1]
    st.caption(f":material/lock: Voiceover / text-to-speech: {reason}")


def subtitle_controls(P, ms) -> None:
    ss = st.session_state
    srt = st.file_uploader("Import SRT/VTT", type=["srt", "vtt"], key="srt_in", label_visibility="collapsed")
    clip_idx = 0
    if srt is not None and len(ms) > 1:
        clip_idx = st.selectbox("For clip", range(len(ms)), format_func=lambda i: ms[i]["name"], key="srt_clip_i")
    if srt is not None and st.button("Use these subtitles", key="srt_go", width="stretch",
                                     icon=":material/subtitles:"):
        cues = analysis.parse_srt(srt.getvalue().decode("utf-8", errors="replace"))
        P.set_cues([{"clip": clip_idx, **c} for c in cues] + [c for c in P.cues if c["clip"] != clip_idx])
        P.set_skill("captions.burn", P.skills.get("captions.burn", {"font_scale": 0.045, "box": True}))
        st.rerun()
    tr = registry.get("captions.transcribe")
    if tr.available:
        if st.button("Auto-generate subtitles", key="tr_go", width="stretch", icon=":material/mic:",
                     disabled=not ms):
            with st.spinner("Transcribing speech…"):
                from video_editor.skills import PlanCtx, Seg, transcribe
                clips = [ffmpeg_ops.probe_video(Path(p)) for p in P.sources]
                ctx = PlanCtx(clips=clips, segments=[Seg(i, 0, c.duration) for i, c in enumerate(clips)])
                transcribe(ctx, {"model": ss.settings["whisper_model"]})
            P.set_cues(ctx.cues)
            P.set_skill("captions.burn", {"font_scale": 0.045, "box": True})
            st.rerun()
    else:
        st.caption(f":material/lock: Auto-generate: {tr.status()[1]}")
    if P.cues:
        toggle_skill(P, "captions.burn", "Burn subtitles into video", {"font_scale": 0.045, "box": True})
        st.caption(f"{len(P.cues)} subtitle lines · select one on the timeline to edit")


def text_controls(P, ms) -> None:
    st.markdown("##### Title")
    t = P.skills.get("graphics.title", {})
    text = st.text_input("Title text", t.get("text", ""), key=_k(P, "ti_text"))
    c1, c2 = st.columns(2)
    start = c1.number_input("Start (s)", 0.0, 3600.0, float(t.get("start", st.session_state.get("playhead", 0.0))), 0.5,
                            key=_k(P, "ti_start"))
    dur = c2.number_input("Length (s)", 0.5, 60.0, float(t.get("duration", 3.0)), 0.5, key=_k(P, "ti_dur"))
    pos = st.selectbox("Position", ["center", "top", "bottom"], index=["center", "top", "bottom"].index(
        t.get("position", "center")), key=_k(P, "ti_pos"))
    if text.strip():
        P.set_skill("graphics.title", {"text": text.strip(), "start": start, "duration": dur, "position": pos})
    elif "graphics.title" in P.skills:
        P.set_skill("graphics.title", None)
    st.markdown("##### Lower third")
    lt = P.skills.get("graphics.lower_third", {})
    name = st.text_input("Name", lt.get("name", ""), key=_k(P, "lt_name"))
    sub = st.text_input("Subtitle", lt.get("subtitle", ""), key=_k(P, "lt_sub"))
    if name.strip():
        P.set_skill("graphics.lower_third", {"name": name.strip(), "subtitle": sub, "start": lt.get("start", 0.5),
                                             "duration": lt.get("duration", 4.0)})
    elif "graphics.lower_third" in P.skills:
        P.set_skill("graphics.lower_third", None)


def _tool_stickers(P, ms) -> None:
    st.caption("Image / logo overlay (PNG with transparency).")
    w = P.skills.get("graphics.watermark")
    up = st.file_uploader("PNG", type=["png"], key="wm_up", label_visibility="collapsed")
    if up is not None:
        path = str(state.save_upload(up, "assets"))
        if not w or w.get("path") != path:
            P.set_skill("graphics.watermark", {"path": path, "position": "bottom_right", "scale": 0.15,
                                               "opacity": 0.85})
            st.rerun()
    if w:
        pos = st.selectbox("Position", ["top_left", "top_right", "bottom_left", "bottom_right"],
                           index=["top_left", "top_right", "bottom_left", "bottom_right"].index(w["position"]),
                           key=_k(P, "wm_pos"))
        slider_skill(P, "graphics.watermark", "scale", "Size", 0.15, 0.03, 0.5, 0.01)
        slider_skill(P, "graphics.watermark", "opacity", "Opacity", 0.85, 0.1, 1.0, 0.05)
        if pos != w["position"]:
            P.set_skill("graphics.watermark", {**P.skills["graphics.watermark"], "position": pos})
        if st.button("Remove", key="wm_rm", icon=":material/delete:"):
            P.set_skill("graphics.watermark", None)
            st.rerun()
    st.caption(":material/lock: Animated stickers: not built (no sticker library).")


def _tool_effects(P, ms) -> None:
    if toggle_skill(P, "fx.denoise", "Denoise video"):
        slider_skill(P, "fx.denoise", "strength", "Strength", 3.0, 0.5, 10.0, 0.5)
    if toggle_skill(P, "fx.sharpen", "Sharpen"):
        slider_skill(P, "fx.sharpen", "amount", "Amount", 0.8, 0.1, 2.0, 0.1)
    if toggle_skill(P, "fx.vignette", "Vignette"):
        slider_skill(P, "fx.vignette", "angle", "Strength", 0.6, 0.1, 1.5, 0.05)
    if toggle_skill(P, "fx.punch_in", "Punch-in zoom"):
        slider_skill(P, "fx.punch_in", "zoom", "Zoom", 1.15, 1.02, 2.0, 0.01)
    for sid in ("fx.stabilize",):
        c = registry.get(sid)
        st.caption(f":material/lock: {c.name}: {c.status()[1]}")


def _tool_transitions(P, ms) -> None:
    cur = P.skills.get("transition.crossfade")
    boundaries = 0
    for i, s in enumerate(P.segments[1:], 1):
        if s.get("break") or s["clip"] != P.segments[i - 1]["clip"]:
            boundaries += 1
    st.caption(f"{boundaries} scene boundar{'y' if boundaries == 1 else 'ies'} "
               "(between different clips or AI-selected moments)")
    cols = st.columns(2)
    for i, name in enumerate(TRANSITIONS):
        if cols[i % 2].button(name, key=f"tr_{name}", width="stretch",
                              type="primary" if cur and cur["type"] == name else "secondary"):
            P.set_skill("transition.crossfade", {"type": name, "duration": (cur or {}).get("duration", 0.5)})
            st.rerun()
    if cur:
        slider_skill(P, "transition.crossfade", "duration", "Duration (s)", 0.5, 0.1, 3.0, 0.1)
        if st.button("Remove transitions", key="tr_rm", icon=":material/delete:", width="stretch"):
            P.set_skill("transition.crossfade", None)
            st.rerun()


def _tool_filters(P, ms) -> None:
    cur = P.skills.get("color.look", {}).get("look")
    cols = st.columns(2)
    for i, lk in enumerate(LOOKS):
        if cols[i % 2].button(lk.title() if lk != "bw" else "B&W", key=f"lk_{lk}", width="stretch",
                              type="primary" if cur == lk else "secondary"):
            P.set_skill("color.look", {"look": lk})
            st.rerun()
    if cur and st.button("No filter", key="lk_none", icon=":material/block:", width="stretch"):
        P.set_skill("color.look", None)
        st.rerun()
    lut = st.file_uploader("LUT (.cube)", type=["cube"], key="lut_up")
    if lut is not None:
        path = str(state.save_upload(lut, "assets"))
        if P.skills.get("color.lut", {}).get("path") != path:
            P.set_skill("color.lut", {"path": path})
            st.rerun()
    if "color.lut" in P.skills and st.button("Remove LUT", key="lut_rm", icon=":material/delete:"):
        P.set_skill("color.lut", None)
        st.rerun()


def _tool_ai(P, ms) -> None:
    st.caption("Use **AI Auto Edit** in the top bar to run silence removal, scene cutting, highlights, "
               "subtitles, transitions and music in one go.")
    for sid in ("fx.stabilize", "cut.beat_sync", "cut.jl_cuts", "cut.speed_ramp", "ext.ai_masking",
                "ext.generative_video"):
        c = registry.get(sid)
        st.caption(f":material/lock: **{c.name}** — {c.status()[1]}")


# ------------------------------------------------------------------ right: properties
def right_panel(P, ms) -> None:
    ss = st.session_state
    sel = ss.get("sel")
    seg = next((s for s in P.segments if sel and sel["kind"] == "seg" and s["id"] == sel["id"]), None)
    if sel and sel["kind"] == "cue":
        cue = next((c for c in P.cues if c["id"] == sel["id"]), None)
        if cue:
            st.markdown("**Subtitle**")
            new = st.text_area("Text", cue["text"], key=_k(P, "cue_t", cue["id"]), height=100,
                               label_visibility="collapsed")
            if new.strip() and new.strip() != cue["text"]:
                P.update_cue_text(cue["id"], new)
            st.caption(f"{_fmt(cue['start'])} – {_fmt(cue['end'])} in source clip {cue['clip'] + 1}")
            if st.button("Delete subtitle", key="cue_del", icon=":material/delete:", width="stretch"):
                P.set_cues([c for c in P.cues if c["id"] != cue["id"]])
                ss.sel = None
                st.rerun()
            return
    if sel and sel["kind"] == "music" and "audio.music_bed" in P.skills:
        st.markdown("**Music**")
        slider_skill(P, "audio.music_bed", "volume", "Volume", 0.25, 0.02, 1.0, 0.01)
        toggle_skill(P, "audio.music_bed", "Duck under speech")  # keeps skill on
        return
    if sel and sel["kind"] == "fx" and sel["id"] in P.skills:
        cap = registry.get(sel["id"])
        st.markdown(f"**{cap.name}**")
        _generic(P, cap)
        if st.button("Remove effect", key="fx_rm", icon=":material/delete:", width="stretch"):
            P.set_skill(sel["id"], None)
            ss.sel = None
            st.rerun()
        return

    title = "Clip" if seg else "Project"
    if seg:
        m = ms[seg["clip"]]
        st.markdown(f"**{m['name']}**")
        st.caption(f"{_fmt(seg['end'] - seg['start'])} selected of {_fmt(m['duration'])}")
    else:
        st.markdown("**Project**")
        st.caption("Select a clip on the timeline to trim it.")
    t_video, t_audio, t_speed, t_adjust = st.tabs(
        [":material/videocam:", ":material/graphic_eq:", ":material/speed:", ":material/tune:"])
    with t_video:
        if seg:
            m = ms[seg["clip"]]
            a = st.number_input("In (s)", 0.0, float(m["duration"]), float(seg["start"]), 0.1, key=_k(P, "in", seg["id"]))
            b = st.number_input("Out (s)", 0.0, float(m["duration"]), float(seg["end"]), 0.1, key=_k(P, "out", seg["id"]))
            if (a, b) != (seg["start"], seg["end"]):
                segs = [dict(s, start=a, end=b) if s["id"] == seg["id"] else s for s in P.segments]
                probs = P.set_segments(segs, {i: x["duration"] for i, x in enumerate(ms)})
                if probs:
                    st.warning("; ".join(probs))
                else:
                    st.rerun()
            _scope("This clip")
        aspect = st.selectbox("Aspect ratio", list(validate.ASPECTS), index=list(validate.ASPECTS).index(
            P.export["aspect"]) if P.export["aspect"] in validate.ASPECTS else 0, key=_k(P, "asp"))
        fit = st.selectbox("Fit", list(validate.FITS), index=list(validate.FITS).index(P.export["fit"]),
                           format_func={"crop": "Fill (crop)", "blur": "Blurred bars", "pad": "Black bars"}.get,
                           key=_k(P, "fit"))
        res = st.selectbox("Resolution", [720, 1080, 1440], index=[720, 1080, 1440].index(P.export["short_edge"])
                           if P.export["short_edge"] in (720, 1080, 1440) else 1, key=_k(P, "res"))
        if (aspect, fit, res) != (P.export["aspect"], P.export["fit"], P.export["short_edge"]):
            P.set_export(aspect=aspect, fit=fit, short_edge=res)
            st.rerun()
        _scope("Whole video")
    with t_audio:
        toggle_skill(P, "audio.clean", "Clean voice (denoise)")
        if toggle_skill(P, "audio.loudnorm", "Normalize loudness"):
            slider_skill(P, "audio.loudnorm", "target_lufs", "Target (LUFS)", -14.0, -24.0, -9.0, 0.5)
        if toggle_skill(P, "audio.volume", "Voice gain"):
            slider_skill(P, "audio.volume", "gain_db", "Gain (dB)", 0.0, -20.0, 12.0, 0.5)
        if toggle_skill(P, "audio.fades", "Audio fades"):
            slider_skill(P, "audio.fades", "fade_in", "Fade in (s)", 0.3, 0.0, 5.0, 0.1)
            slider_skill(P, "audio.fades", "fade_out", "Fade out (s)", 0.8, 0.0, 5.0, 0.1)
        _scope("Whole video")
    with t_speed:
        cur = P.skills.get("time.speed", {}).get("factor", 1.0)
        f = st.slider("Speed", 0.25, 4.0, float(cur), 0.05, key=_k(P, "spd"), format="%.2fx")
        if f != cur:
            P.set_skill("time.speed", None if abs(f - 1.0) < 1e-6 else {"factor": f})
            st.rerun()
        _scope("Whole video (per-clip speed isn't supported by the renderer)")
    with t_adjust:
        ca = P.skills.get("color.adjust", {})
        vals = {}
        for name, lo, hi, d in (("brightness", -0.5, 0.5, 0.0), ("contrast", 0.5, 2.0, 1.0),
                                ("saturation", 0.0, 2.5, 1.0), ("gamma", 0.5, 2.0, 1.0)):
            vals[name] = st.slider(name.title(), lo, hi, float(ca.get(name, d)), 0.02, key=_k(P, "adj", name))
        if toggle_skill(P, "color.temperature", "White balance"):
            slider_skill(P, "color.temperature", "kelvin", "Temperature (K)", 5500, 2500, 9000, 100)
        neutral = vals == {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "gamma": 1.0}
        if neutral and "color.adjust" in P.skills:
            P.set_skill("color.adjust", None)
        elif not neutral and vals != {k: ca.get(k) for k in vals}:
            P.set_skill("color.adjust", vals)
        _scope("Whole video")


def _generic(P, cap) -> None:
    cur = P.skills.get(cap.id, {})
    out = dict(cur)
    for s in cap.settings:
        v = cur.get(s.name, s.default)
        k = _k(P, "g", cap.id, s.name)
        if s.type == "float":
            out[s.name] = st.slider(s.name, float(s.min), float(s.max), float(v), 0.01, key=k)
        elif s.type == "int":
            out[s.name] = st.slider(s.name, int(s.min), int(s.max), int(v), key=k)
        elif s.type == "bool":
            out[s.name] = st.checkbox(s.name, bool(v), key=k)
        elif s.type == "choice":
            out[s.name] = st.selectbox(s.name, list(s.choices), list(s.choices).index(v), key=k)
    if out != cur:
        P.set_skill(cap.id, out)


