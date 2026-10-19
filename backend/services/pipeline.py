"""Job handlers: Upload -> Analyze -> Plan edit -> Generate timeline -> Render -> Preview -> Export."""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from .. import config
from ..schemas import Edl, ProjectDoc
from ..workers import jobs
from ..workers.jobs import JobContext, JobFailed
from . import analysis, beats, editing, instructions, matting, music_library, music_reco, preferences, projects, rendering, system, textvideo
from . import media as media_svc
from .media import STILL_SECONDS


# ------------------------------------------------------------------ ingest
@jobs.handler("ingest")
def ingest(ctx: JobContext, pid: str, params: dict) -> dict:
    ctx.stage("process")
    m = media_svc.process(params["mediaId"], lambda f, msg: ctx.update(f, msg))
    return {"mediaId": m["id"]}


@jobs.handler("ingest:failed")
def ingest_failed(pid: str, params: dict, error: str) -> None:
    media_svc.mark_failed(params["mediaId"], error)


# ------------------------------------------------------------------ helpers
def _music_path(media_id: str) -> Path:
    """Resolve a music mediaId to a file, whether it's a real uploaded media row or one of
    the bundled, real, CC-BY-licensed library tracks (see music_library.py)."""
    if music_library.is_library_id(media_id):
        return music_library.resolve_path(media_id)
    return media_svc.render_path(media_id)


def _music_row(doc: ProjectDoc) -> dict | None:
    st = doc.settings
    if st.musicSource == "none" or not st:
        return None
    if st.musicSource == "upload":
        mid = st.musicId
        if not mid:
            return None
        row = media_svc.get_row(mid)
        if row is None or row["kind"] != "audio":
            raise JobFailed("The selected background music file no longer exists. Choose another track or turn music off.")
        if row["status"] != "ready":
            raise JobFailed(f"Background music '{row['name']}' is still processing or failed to process.")
        return row
    if st.musicSource in ("library", "auto"):
        mood = st.musicMood or music_library.auto_mood(doc.style)
        track = music_library.by_mood(mood)
        if track is None:
            # Should be unreachable (the 5 moods in schemas.MusicMood all have a real track), but
            # never silently pretend music is playing if the catalog doesn't actually have it.
            return None
        return {"id": track["id"], "name": track["title"], "kind": "audio", "status": "ready",
                "has_audio": True, "duration": track["duration"]}
    return None


def _captions_for(rows: list[dict], ctx: JobContext, notes: list[str], language: str = "auto") -> list[dict]:
    st = system.status()["transcription"]
    if not st["ok"]:
        notes.append(f"Captions skipped: speech-to-text is not installed ({st['hint']}).")
        return []
    with_audio = [m for m in rows if m["has_audio"]]
    if not with_audio:
        notes.append("Captions skipped: the selected footage has no audio track.")
        return []
    captions: list[dict] = []
    for i, m in enumerate(with_audio):
        name = m["name"]
        ctx.update(i / len(with_audio), f"Transcribing {name}")
        tr = analysis.transcript(m, preferences.whisper_model(),
                                 lambda f, i=i, name=name: ctx.update((i + f) / len(with_audio), f"Transcribing {name}"),
                                 language=language)
        for c in tr.get("cues", []):
            cap: dict = {"id": "t" + uuid.uuid4().hex[:8], "mediaId": m["id"], "srcStart": round(c["start"], 3),
                         "srcEnd": round(c["end"], 3), "text": c["text"]}
            if c.get("words"):
                cap["words"] = c["words"]
            captions.append(cap)
    if captions:
        notes.append(f"Transcribed {len(captions)} caption(s) locally with faster-whisper ({preferences.whisper_model()}).")
    else:
        notes.append("Captions: no speech was detected, so no captions were added.")
    return captions


FILLERS = {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "hmm", "hm", "mm", "mmm", "ah", "eh", "嗯", "呃", "額", "唔"}
FILLER_PAD = 0.04          # seconds trimmed around a filler so the cut does not clip neighbouring words


def _mark_fillers(rows: list[dict], data: dict, ctx: JobContext, language: str) -> int:
    """Transcribe (cached, so the caption step reuses it) and add each spoken filler to the media's silences, which the
    editor already cuts out. Returns how many were found."""
    st = system.status()["transcription"]
    if not st["ok"]:
        return 0
    found = 0
    spoken = [m for m in rows if m["kind"] == "video" and m["has_audio"]]
    for i, m in enumerate(spoken):
        label = f"Listening for filler words in {m['name']}"
        tr = analysis.transcript(m, preferences.whisper_model(), lambda f, i=i, label=label: ctx.update((i + f) / len(spoken), label),
                                 language=language)
        extra = []
        for cue in tr.get("cues", []):
            for w in cue.get("words") or []:
                token = "".join(ch for ch in w["word"].lower() if ch.isalnum())
                if token in FILLERS and w["end"] - w["start"] >= 0.08:
                    extra.append([round(w["start"] + FILLER_PAD, 3), round(w["end"] - FILLER_PAD, 3)])
        if extra:
            data[m["id"]]["audio"]["fillers"] = extra
            found += len(extra)
    return found


def _render_preview(ctx: JobContext, pid: str, edl: dict, resolution: int) -> dict:
    out = config.project_dir(pid) / "renders" / f"preview_{ctx.id}.mp4"
    res = rendering.render(edl, rendering.preview_export(resolution), out, lambda f, msg: ctx.update(f, msg))
    ctx.stage("finalize")
    render = {"id": ctx.id, "url": media_svc.url_for(out), "duration": res["duration"], "width": res["width"],
              "height": res["height"], "size": res["size"], "edl": edl, "jobId": ctx.id, "createdAt": time.time(),
              "warnings": res["warnings"]}
    # The previous current version moves into history (see projects.set_render) instead of being
    # deleted; only versions pushed out past the history cap have their preview file removed.
    dropped = projects.set_render(pid, render)
    for old in dropped:
        if old.get("id"):
            (out.parent / f"preview_{old['id']}.mp4").unlink(missing_ok=True)
    return render


def _store_edl(pid: str, edl: dict) -> None:
    current = ProjectDoc.model_validate(projects.get(pid)["doc"])
    current.edl = Edl.model_validate(edl)
    projects.update(pid, doc=current)


# ------------------------------------------------------------------ generate
@jobs.handler("generate")
def generate(ctx: JobContext, pid: str, params: dict) -> dict:
    doc = ProjectDoc.model_validate(params["doc"])
    plan = None
    if doc.settings.instruction.strip():
        plan = instructions.parse(doc.settings.instruction)
        doc = instructions.apply(doc, plan)       # a new, validated document; the stored one is untouched
    rows = analysis.media_rows(pid, ("video", "image"))
    if not rows:
        raise JobFailed("Upload at least one video or image before generating.")
    busy = [m["name"] for m in rows if m["status"] == "processing"]
    if busy:
        raise JobFailed(f"Wait for {len(busy)} file(s) to finish processing: {', '.join(busy[:3])}.")
    ready = [m for m in rows if m["status"] == "ready"]
    if not ready:
        raise JobFailed("None of the uploaded files could be processed. Remove them and upload again.")
    auto_pick = doc.settings.musicSource == "auto" and not doc.settings.musicMood
    music_row = None if auto_pick else _music_row(doc)

    ctx.stage("analyze")
    data: dict = {}
    for i, m in enumerate(ready):
        label = f"Analyzing {m['name']}"
        ctx.update(i / len(ready), label)
        vis = analysis.visual_features(m, lambda f, i=i, label=label: ctx.update((i + 0.9 * f) / len(ready), label))
        aud = analysis.audio_features(m) if m["kind"] == "video" else {"silences": [], "energy": [], "step": 0.5}
        data[m["id"]] = {"visual": vis, "audio": aud}

    ctx.stage("scenes")
    scene_total = 0
    videos = [m for m in ready if m["kind"] == "video"]
    for i, m in enumerate(ready):
        if m["kind"] == "image":
            data[m["id"]]["scenes"] = [[0.0, STILL_SECONDS]]
            continue
        if doc.settings.sceneDetection:
            label = f"Detecting scenes in {m['name']}"
            res = analysis.scenes(m, lambda f, i=i, label=label: ctx.update((i + f) / len(ready), label))
            data[m["id"]]["scenes"] = res["scenes"]
        else:
            data[m["id"]]["scenes"] = [[0.0, float(m["duration"])]]
        scene_total += len(data[m["id"]]["scenes"])

    ctx.stage("highlights")
    if auto_pick:        # no mood asked for: choose the track that suits what was actually filmed
        profile = music_reco.footage_profile(ready, data)
        top = music_reco.recommend(profile, doc.style if doc.style != "auto" else "cinematic")[0]
        doc.settings.musicMood = top["mood"]
        music_row = _music_row(doc)
    beat = None
    if music_row is not None and doc.settings.beatSync and doc.style in ("dynamic", "energetic", "auto"):
        ctx.update(0.3, "Finding the music's beat")
        beat = beats.estimate(str(_music_path(music_row["id"])))
    fillers = 0
    if doc.settings.removeFillers and doc.settings.removeSilence and doc.settings.captions:
        fillers = _mark_fillers(ready, data, ctx, doc.settings.subtitleLanguage)
    try:
        edl = editing.build_edl(doc, ready, data, music_row, beat, on_stage=ctx.stage)
    except ValueError as e:
        raise JobFailed(str(e))
    if videos:
        engine = "PySceneDetect" if doc.settings.sceneDetection else "scene detection off"
        edl["notes"].insert(1, f"Analyzed {len(ready)} file(s): {scene_total} scene(s) ({engine}).")

    if fillers:
        edl["notes"].insert(1, f"Cut {fillers} filler word(s) (um, uh, ...).")
    if plan is not None:
        edl["plan"] = {"instruction": doc.settings.instruction, "understood": plan["understood"], "warnings": plan["warnings"]}
        if plan["understood"]:
            edl["notes"].insert(1, "Understood your request: " + ", ".join(plan["understood"]) + ".")
    Edl.model_validate(edl)  # schema check before anything is rendered

    ctx.stage("audio_captions")
    if doc.settings.captions:
        used = {c["mediaId"] for c in edl["clips"]}
        edl["captions"] = _captions_for([m for m in ready if m["id"] in used], ctx, edl["notes"],
                                        doc.settings.subtitleLanguage)
    if music_row is not None:
        edl["notes"].append(f"Background music: {music_row['name']}"
                            + (" (ducked under speech)." if edl["music"]["duck"] else "."))
    if doc.settings.normalizeAudio:
        edl["notes"].append(f"Loudness normalized to {edl['audio']['lufs']:.0f} LUFS.")

    ctx.stage("render")
    render = _render_preview(ctx, pid, edl, doc.settings.resolution)
    _store_edl(pid, edl)
    applied = {"style": doc.style, "aspect": doc.aspect, "template": doc.template, "settings": doc.settings.model_dump()}
    return {"edl": edl, "render": render, "appliedDoc": applied}


# ------------------------------------------------------------------ text to video
@jobs.handler("textvideo")
def textvideo_job(ctx: JobContext, pid: str, params: dict) -> dict:
    """Description only: plan scenes, generate each with the configured provider, then edit them together."""
    doc = ProjectDoc.model_validate(params["doc"])
    parsed = instructions.parse(doc.settings.instruction)      # length / format / music hints in the text
    doc = instructions.apply(doc, parsed)
    st = doc.settings
    ctx.stage("plan")
    if not textvideo.status()["configured"]:
        raise JobFailed(textvideo.SETUP_HINT)
    sp = textvideo.plan(st.instruction, st.targetDuration, doc.aspect)
    aspect = doc.aspect if doc.aspect != "original" else "16:9"
    n = sp["sceneCount"]

    ctx.stage("scenes")
    rows: list[dict] = []
    try:
        for i, prompt in enumerate(sp["scenes"]):
            label = f"Generating scene {i + 1} of {n}"
            ctx.update(i / n, label)
            url = textvideo.generate_scene(prompt, aspect, ctx.check)
            ctx.update((i + 0.9) / n, f"Downloading scene {i + 1} of {n}")
            row = textvideo.download(url, pid, f"AI scene {i + 1}.mp4")
            media_svc.process(row["id"])
            row = media_svc.get_row(row["id"])
            if row["status"] != "ready":
                raise JobFailed(f"Scene {i + 1} was generated but could not be processed: {row.get('error') or 'unknown error'}")
            rows.append(row)
    except JobFailed as e:
        if rows:
            raise JobFailed(f"{e} The {len(rows)} scene(s) already generated were kept in your media library.")
        raise

    ctx.stage("assemble")
    style = doc.style if doc.style in editing.STYLES else "cinematic"
    spec = editing.STYLES[style]
    transition = {"type": spec.transition[0], "duration": spec.transition[1]} if st.transitions else None
    clips = [{"id": "c" + uuid.uuid4().hex[:8], "mediaId": r["id"], "srcStart": 0.0, "srcEnd": float(r["duration"]),
              "sceneBreak": True, "label": f"Scene {i + 1}"} for i, r in enumerate(rows)]
    from . import layout as lay, templates
    lt = lay.layout(clips, transition)
    notes = [f"Generated {n} scene(s) of about {sp['clipSeconds']:g}s with {textvideo.status()['model']} from your description ({sp['chars']:,} characters).",
             *sp["notes"],
             "Voiceover and subtitles are not available for generated video yet; add text on the timeline instead."]
    if st.targetDuration and abs(lt["duration"] - st.targetDuration) > sp["clipSeconds"]:
        notes.append(f"Length is {lt['duration']:.0f}s: the provider generates fixed-length scenes, so it can differ from the {st.targetDuration:.0f}s you asked for.")
    music_row = _music_row(doc)
    music = None
    if music_row is not None:
        music = {"mediaId": music_row["id"], "volume": st.musicVolume, "duck": any(r["has_audio"] for r in rows)}
        notes.append(f"Background music: {music_row['name']}.")
    tpl = templates.get(doc.template)
    template_rec, title_specs = (templates.lay_out(tpl, clips, lt["duration"]) if tpl else (None, []))
    notes.append(f"{len(clips)} clips, {lt['duration']:.1f}s total.")
    edl = {"version": 1, "style": doc.style, "aspect": doc.aspect, "fit": "crop", "clips": clips,
           "transition": transition, "look": st.look or spec.look, "music": music, "captions": [],
           "burnCaptions": False, "titles": [{"id": "t" + uuid.uuid4().hex[:8], **t} for t in title_specs],
           "template": template_rec,
           "audioClips": ([{"id": "a" + uuid.uuid4().hex[:7], "mediaId": music["mediaId"], "kind": "music", "start": 0.0,
                            "trimIn": 0.0, "duration": None, "volume": music["volume"], "fadeIn": 0.0, "fadeOut": 0.0,
                            "loop": True, "duck": music["duck"]}] if music else []),
           "markers": [], "audio": {"normalize": st.normalizeAudio, "lufs": spec.lufs, "clean": False, "fades": False},
           "notes": notes,
           "plan": {"instruction": st.instruction, "understood": [f"{n} generated scene(s)", *parsed["understood"]],
                    "warnings": [*sp["notes"], *parsed["warnings"]]}}
    Edl.model_validate(edl)

    ctx.stage("render")
    render = _render_preview(ctx, pid, edl, st.resolution)
    _store_edl(pid, edl)
    applied = {"style": doc.style, "aspect": doc.aspect, "template": doc.template, "settings": st.model_dump()}
    return {"edl": edl, "render": render, "appliedDoc": applied}


# ------------------------------------------------------------------ re-render after timeline edits
@jobs.handler("render")
def render_preview(ctx: JobContext, pid: str, params: dict) -> dict:
    doc = ProjectDoc.model_validate(params["doc"])
    if doc.edl is None or not doc.edl.clips:
        raise JobFailed("The timeline is empty. Generate an AI edit first.")
    edl = doc.edl.model_dump()
    ctx.stage("render")
    try:
        render = _render_preview(ctx, pid, edl, doc.settings.resolution)
    except rendering.RenderError as e:
        raise JobFailed(str(e))
    return {"render": render}


# ------------------------------------------------------------------ export
@jobs.handler("export")
def export(ctx: JobContext, pid: str, params: dict) -> dict:
    doc = ProjectDoc.model_validate(params["doc"])
    if doc.edl is None or not doc.edl.clips:
        raise JobFailed("Nothing to export yet. Generate an AI edit first.")
    settings = doc.export.model_dump()
    folder = config.project_dir(pid) / "exports"
    stem = rendering.safe_filename(settings["filename"])
    out = folder / f"{stem}.mp4"
    n = 2
    while out.exists():
        out = folder / f"{stem}-{n}.mp4"
        n += 1
    edl = doc.edl.model_dump()
    handling = settings.get("subtitleHandling", "burn")
    if handling != "burn":
        edl["burnCaptions"] = False  # "srt" writes a sidecar file instead; "none" drops captions entirely
    export_cfg = rendering.final_export(settings)
    ctx.stage("render")
    try:
        res = rendering.render(edl, export_cfg, out, lambda f, msg: ctx.update(f, msg))
    except rendering.RenderError as e:
        raise JobFailed(str(e))
    ctx.stage("finalize")
    rendering.write_sidecar(out, edl, export_cfg)
    srt_path = None
    if handling == "srt":
        srt_text = rendering.build_subtitle_text(edl, "srt")
        if srt_text:
            srt_path = out.with_suffix(".srt")
            srt_path.write_text(srt_text)
    return {"path": str(out), "folder": str(out.parent), "url": media_svc.url_for(out), "filename": out.name,
            "size": res["size"], "duration": res["duration"], "width": res["width"], "height": res["height"],
            "fps": res["fps"], "warnings": res["warnings"],
            "subtitlesFile": srt_path.name if srt_path else None}


# ------------------------------------------------------------------ AI background removal
@jobs.handler("matte")
def matte(ctx: JobContext, pid: str, params: dict) -> dict:
    m = media_svc.get_row(params["mediaId"])
    if m is None or m["project_id"] != pid:
        raise JobFailed("That video no longer exists.")
    if m["kind"] != "video" or m["status"] != "ready":
        raise JobFailed("AI Background Removal needs a video that has finished processing.")
    ctx.stage("matte")
    try:
        matting.compute_matte(m, lambda f, msg: ctx.update(f, msg), force=bool(params.get("force")))
    except matting.MattingError as e:
        raise JobFailed(str(e))
    meta = matting._meta_path(m)
    import json as _json
    return {"mediaId": m["id"], **(_json.loads(meta.read_text()) if meta.exists() else {})}


# ------------------------------------------------------------------ captions on demand
@jobs.handler("transcribe")
def transcribe(ctx: JobContext, pid: str, params: dict) -> dict:
    doc = ProjectDoc.model_validate(params["doc"])
    if doc.edl is None or not doc.edl.clips:
        raise JobFailed("Generate an edit first: captions are created for the clips on the timeline.")
    used = {c.mediaId for c in doc.edl.clips}
    rows = [m for m in analysis.media_rows(pid, ("video",)) if m["id"] in used and m["status"] == "ready"]
    ctx.stage("audio_captions")
    notes: list[str] = []
    captions = _captions_for(rows, ctx, notes, doc.settings.subtitleLanguage)
    return {"captions": captions, "notes": notes}


def output_path(job: dict) -> Path | None:
    p = (job.get("result") or {}).get("path")
    if not p:
        return None
    path = Path(p).resolve()
    return path if config.DATA_DIR in path.parents and path.exists() else None
