import platform
import subprocess
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..schemas import ExportRequest, GenerateRequest, ProjectDoc
from ..services import analysis, imagevideo, media as media_svc, pipeline, projects, rendering, textvideo
from ..workers import jobs

router = APIRouter(tags=["jobs"])


def _start(kind: str, pid: str, body) -> dict:
    try:
        projects.get(pid)
    except projects.NotFound as e:
        raise HTTPException(404, str(e))
    running = jobs.active(pid, kind)
    if running:
        raise HTTPException(409, f"A {kind} job is already running for this project.")
    # Persist the settings the job runs with, so a reload shows exactly what was generated.
    projects.update(pid, doc=body.doc)
    return jobs.submit(kind, pid, {"doc": body.doc.model_dump()})


@router.post("/api/projects/{pid}/generate", status_code=202)
def generate(pid: str, body: GenerateRequest):
    """Footage in the project -> edit it; a description alone -> generate video from text."""
    try:
        projects.get(pid)
    except projects.NotFound as e:
        raise HTTPException(404, str(e))
    has_footage = bool(analysis.media_rows(pid, ("video", "image")))
    text = body.doc.settings.instruction.strip()
    if not has_footage and not text:
        raise HTTPException(422, "Upload a video or image, or describe the video you want to generate.")
    kind = "textvideo" if (not has_footage and text) else "generate"
    if jobs.active(pid, "generate" if kind == "textvideo" else "textvideo"):
        raise HTTPException(409, "A generation job is already running for this project.")
    return _start(kind, pid, body)


class AnimateBody(BaseModel):
    mediaId: str
    prompt: str = Field("", max_length=1000)
    seconds: float = Field(5.0, ge=2, le=10)
    aspect: Literal["16:9", "9:16", "1:1", "4:5", "original"] = "16:9"
    intensity: Literal["low", "medium", "high"] = "medium"


@router.get("/api/system/image-to-video")
def image_to_video_status():
    return imagevideo.status()


@router.post("/api/projects/{pid}/animate", status_code=202)
def animate(pid: str, body: AnimateBody):
    """Turn one image of the project into an animated clip with the configured image-to-video provider."""
    try:
        projects.get(pid)
    except projects.NotFound as e:
        raise HTTPException(404, str(e))
    if not imagevideo.status()["configured"]:
        raise HTTPException(503, imagevideo.SETUP_HINT)
    row = media_svc.get_row(body.mediaId)
    if row is None or row["project_id"] != pid or row["kind"] != "image":
        raise HTTPException(422, "Choose an image from this project's media.")
    if jobs.active(pid, "animate"):
        raise HTTPException(409, "An animation is already being generated for this project.")
    return jobs.submit("animate", pid, body.model_dump())


@router.post("/api/projects/{pid}/generation/plan")
def generation_plan(pid: str, body: GenerateRequest):
    """What Generate would do right now, so the UI can say it before the user clicks."""
    from ..workers.jobs import JobFailed
    has_footage = bool(analysis.media_rows(pid, ("video", "image")))
    text = body.doc.settings.instruction.strip()
    mode = "edit" if has_footage else ("text" if text else "none")
    out = {"mode": mode, "textToVideo": textvideo.status()}
    if mode == "text":
        try:
            sp = textvideo.plan(text, body.doc.settings.targetDuration, body.doc.aspect)
            out.update(sceneCount=sp["sceneCount"], seconds=sp["seconds"], notes=sp["notes"], chars=sp["chars"])
        except JobFailed as e:
            out["error"] = str(e)
    return out


@router.post("/api/projects/{pid}/render", status_code=202)
def render(pid: str, body: GenerateRequest):
    return _start("render", pid, body)


@router.post("/api/projects/{pid}/export", status_code=202)
def export(pid: str, body: ExportRequest):
    return _start("export", pid, body)


@router.post("/api/projects/{pid}/transcribe", status_code=202)
def transcribe(pid: str, body: GenerateRequest):
    return _start("transcribe", pid, body)


@router.get("/api/projects/{pid}/jobs")
def project_jobs(pid: str):
    return jobs.list_for(pid)


def _job_or_404(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return _job_or_404(job_id)


@router.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str):
    _job_or_404(job_id)
    return jobs.cancel(job_id)


@router.post("/api/jobs/{job_id}/retry", status_code=202)
def retry(job_id: str):
    job = _job_or_404(job_id)
    if job["status"] in ("queued", "running"):
        raise HTTPException(409, "Job is still running.")
    if jobs.active(job["projectId"], job["kind"]):
        raise HTTPException(409, f"A {job['kind']} job is already running for this project.")
    return jobs.retry(job_id)


@router.get("/api/jobs/{job_id}/download")
def download(job_id: str):
    path = pipeline.output_path(_job_or_404(job_id))
    if path is None:
        raise HTTPException(404, "Output file not found. It may have been deleted; export again.")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.post("/api/jobs/{job_id}/reveal")
def reveal(job_id: str):
    """Show the exported file in the OS file manager (local machine only)."""
    path = pipeline.output_path(_job_or_404(job_id))
    if path is None:
        raise HTTPException(404, "Output file not found.")
    system = platform.system()
    if system == "Darwin":
        cmd = ["open", "-R", str(path)]
    elif system == "Windows":
        cmd = ["explorer", f"/select,{path}"]
    else:
        cmd = ["xdg-open", str(path.parent)]
    try:
        subprocess.Popen(cmd)
    except OSError as e:
        raise HTTPException(501, f"Opening the folder is not supported here: {e}")
    return {"ok": True, "folder": str(path.parent)}


@router.get("/api/projects/{pid}/captions.{fmt}")
def export_captions(pid: str, fmt: str):
    """Export captions as SRT or VTT subtitle file."""
    if fmt not in ("srt", "vtt"):
        raise HTTPException(400, "Supported formats: srt, vtt")
    try:
        proj = projects.get(pid)
    except projects.NotFound as e:
        raise HTTPException(404, str(e))
    doc = ProjectDoc.model_validate(proj["doc"])
    if doc.edl is None or not doc.edl.captions:
        raise HTTPException(404, "No captions available. Generate or transcribe first.")
    body = rendering.build_subtitle_text(doc.edl.model_dump(), fmt)
    if body is None:
        raise HTTPException(404, "No captions fall inside the current clips.")
    media_type = "text/vtt" if fmt == "vtt" else "application/x-subrip"
    name = proj.get("name", "captions").replace(" ", "_")
    return Response(content=body, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})
