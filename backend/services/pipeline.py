"""Job handlers: Upload -> Analyze -> Plan edit -> Generate timeline -> Render -> Preview -> Export."""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from .. import config
from ..schemas import Edl, ProjectDoc
from ..workers import jobs
from ..workers.jobs import JobContext, JobFailed
from . import analysis, beats, editing, projects, rendering, system
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
def _music_row(doc: ProjectDoc) -> dict | None:
    mid = doc.settings.musicId
    if not mid:
        return None
    row = media_svc.get_row(mid)
    if row is None or row["kind"] != "audio":
        raise JobFailed("The selected background music file no longer exists. Choose another track or turn music off.")
    if row["status"] != "ready":
        raise JobFailed(f"Background music '{row['name']}' is still processing or failed to process.")
    return row


def _captions_for(rows: list[dict], ctx: JobContext, notes: list[str]) -> list[dict]:
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
        tr = analysis.transcript(m, config.WHISPER_MODEL,
                                 lambda f, i=i, name=name: ctx.update((i + f) / len(with_audio), f"Transcribing {name}"))
        for c in tr.get("cues", []):
            captions.append({"id": "t" + uuid.uuid4().hex[:8], "mediaId": m["id"], "srcStart": round(c["start"], 3),
                             "srcEnd": round(c["end"], 3), "text": c["text"]})
    if captions:
        notes.append(f"Transcribed {len(captions)} caption(s) locally with faster-whisper ({config.WHISPER_MODEL}).")
    else:
        notes.append("Captions: no speech was detected, so no captions were added.")
    return captions


def _render_preview(ctx: JobContext, pid: str, edl: dict, resolution: int) -> dict:
    out = config.project_dir(pid) / "renders" / f"preview_{ctx.id}.mp4"
    res = rendering.render(edl, rendering.preview_export(resolution), out, lambda f, msg: ctx.update(f, msg))
    ctx.stage("finalize")
    render = {"url": media_svc.url_for(out), "duration": res["duration"], "width": res["width"],
              "height": res["height"], "size": res["size"], "edl": edl, "jobId": ctx.id, "createdAt": time.time(),
              "warnings": res["warnings"]}
    projects.set_render(pid, render)
    for old in out.parent.glob("preview_*.mp4"):
        if old != out:
            old.unlink(missing_ok=True)
    return render


def _store_edl(pid: str, edl: dict) -> None:
    current = ProjectDoc.model_validate(projects.get(pid)["doc"])
    current.edl = Edl.model_validate(edl)
    projects.update(pid, doc=current)


# ------------------------------------------------------------------ generate
@jobs.handler("generate")
def generate(ctx: JobContext, pid: str, params: dict) -> dict:
    doc = ProjectDoc.model_validate(params["doc"])
    rows = analysis.media_rows(pid, ("video", "image"))
    if not rows:
        raise JobFailed("Upload at least one video or image before generating.")
    busy = [m["name"] for m in rows if m["status"] == "processing"]
    if busy:
        raise JobFailed(f"Wait for {len(busy)} file(s) to finish processing: {', '.join(busy[:3])}.")
    ready = [m for m in rows if m["status"] == "ready"]
    if not ready:
        raise JobFailed("None of the uploaded files could be processed. Remove them and upload again.")
    music_row = _music_row(doc)

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
    beat = None
    if music_row is not None and doc.settings.beatSync and doc.style == "dynamic":
        ctx.update(0.3, "Finding the music's beat")
        beat = beats.estimate(str(media_svc.render_path(music_row["id"])))
    try:
        edl = editing.build_edl(doc, ready, data, music_row, beat, on_stage=ctx.stage)
    except ValueError as e:
        raise JobFailed(str(e))
    if videos:
        engine = "PySceneDetect" if doc.settings.sceneDetection else "scene detection off"
        edl["notes"].insert(1, f"Analyzed {len(ready)} file(s): {scene_total} scene(s) ({engine}).")

    Edl.model_validate(edl)  # schema check before anything is rendered

    ctx.stage("audio_captions")
    if doc.settings.captions:
        used = {c["mediaId"] for c in edl["clips"]}
        edl["captions"] = _captions_for([m for m in ready if m["id"] in used], ctx, edl["notes"])
    if music_row is not None:
        edl["notes"].append(f"Background music: {music_row['name']}"
                            + (" (ducked under speech)." if edl["music"]["duck"] else "."))
    if doc.settings.normalizeAudio:
        edl["notes"].append(f"Loudness normalized to {edl['audio']['lufs']:.0f} LUFS.")

    ctx.stage("render")
    render = _render_preview(ctx, pid, edl, doc.settings.resolution)
    _store_edl(pid, edl)
    return {"edl": edl, "render": render}


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
    export_cfg = rendering.final_export(settings)
    ctx.stage("render")
    try:
        res = rendering.render(edl, export_cfg, out, lambda f, msg: ctx.update(f, msg))
    except rendering.RenderError as e:
        raise JobFailed(str(e))
    ctx.stage("finalize")
    rendering.write_sidecar(out, edl, export_cfg)
    return {"path": str(out), "folder": str(out.parent), "url": media_svc.url_for(out), "filename": out.name,
            "size": res["size"], "duration": res["duration"], "width": res["width"], "height": res["height"],
            "fps": res["fps"], "warnings": res["warnings"]}


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
    captions = _captions_for(rows, ctx, notes)
    return {"captions": captions, "notes": notes}


def output_path(job: dict) -> Path | None:
    p = (job.get("result") or {}).get("path")
    if not p:
        return None
    path = Path(p).resolve()
    return path if config.DATA_DIR in path.parents and path.exists() else None
