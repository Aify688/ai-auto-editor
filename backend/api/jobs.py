import platform
import subprocess

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..schemas import ExportRequest, GenerateRequest
from ..services import pipeline, projects
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
    return _start("generate", pid, body)


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
