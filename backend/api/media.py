from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from ..schemas import MediaOrder
from ..services import media, projects
from ..workers import jobs

router = APIRouter(tags=["media"])


def _project_or_404(pid: str) -> None:
    try:
        projects.get(pid)
    except projects.NotFound as e:
        raise HTTPException(404, str(e))


@router.get("/api/projects/{pid}/media")
def list_media(pid: str):
    _project_or_404(pid)
    return media.list_media(pid)


@router.post("/api/projects/{pid}/media", status_code=201)
async def upload(pid: str, file: UploadFile = File(...)):
    _project_or_404(pid)
    try:
        item = await run_in_threadpool(media.save_upload, pid, file.filename or "upload", file.file)
    except media.TooLarge as e:
        raise HTTPException(413, str(e))
    except media.MediaError as e:
        raise HTTPException(400, f"{file.filename}: {e}")
    finally:
        await file.close()
    jobs.submit("ingest", pid, {"mediaId": item["id"]})
    return item


@router.delete("/api/media/{mid}", status_code=204)
def delete_media(mid: str):
    if media.get_row(mid) is None:
        raise HTTPException(404, "Media not found")
    media.delete(mid)


@router.post("/api/media/{mid}/retry")
def retry_media(mid: str):
    row = media.get_row(mid)
    if row is None:
        raise HTTPException(404, "Media not found")
    media.mark_processing(mid)
    jobs.submit("ingest", row["project_id"], {"mediaId": mid})
    return media.get(mid)


@router.put("/api/projects/{pid}/media/order")
def reorder(pid: str, body: MediaOrder):
    _project_or_404(pid)
    try:
        return media.reorder(pid, body.ids)
    except media.MediaError as e:
        raise HTTPException(400, str(e))
