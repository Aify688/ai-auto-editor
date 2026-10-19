from typing import Literal, Optional

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from fastapi.concurrency import run_in_threadpool

from ..schemas import MediaOrder
from ..services import matting, media, projects, tts
from ..workers import jobs

router = APIRouter(tags=["media"])


class BgPreview(BaseModel):
    t: float = 0.0
    mode: Literal["color", "image", "video", "blur"] = "color"
    color: str = "#00B140"
    blur: float = Field(50, ge=0, le=100)
    bgMediaId: Optional[str] = None


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


class TtsBody(BaseModel):
    text: str = Field(min_length=1, max_length=tts.MAX_CHARS)
    voice: str
    rate: float = Field(1.0, ge=0.5, le=2.0)


@router.post("/api/projects/{pid}/tts", status_code=201)
async def text_to_speech(pid: str, body: TtsBody):
    """Speak `text` with a local voice and add the result to the project's media like an upload."""
    _project_or_404(pid)
    import tempfile
    from pathlib import Path
    words = " ".join(body.text.split()[:4])[:40] or "Voiceover"
    safe = "".join(ch for ch in words if ch.isalnum() or ch in " -_") .strip() or "Voiceover"
    with tempfile.TemporaryDirectory(prefix="ave_tts_up_") as tmp:
        wav = Path(tmp) / f"Voiceover - {safe}.wav"
        try:
            await run_in_threadpool(tts.synthesize, body.text, body.voice, body.rate, wav)
            with open(wav, "rb") as fh:
                item = await run_in_threadpool(media.save_upload, pid, wav.name, fh)
        except tts.TtsError as e:
            raise HTTPException(400, str(e))
        except media.MediaError as e:
            raise HTTPException(400, str(e))
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


@router.post("/api/media/{mid}/matte", status_code=202)
def start_matte(mid: str, force: bool = False):
    """Find the subject of a video once (cached) so AI Background Removal can be rendered."""
    m = media.get_row(mid)
    if m is None:
        raise HTTPException(404, "Media not found")
    if m["kind"] != "video":
        raise HTTPException(400, "AI Background Removal works on videos.")
    if jobs.active(m["project_id"], "matte"):
        raise HTTPException(409, "Subject detection is already running for this project.")
    return jobs.submit("matte", m["project_id"], {"mediaId": mid, "force": force})


@router.get("/api/media/{mid}/matte")
def matte_status(mid: str):
    m = media.get_row(mid)
    if m is None:
        raise HTTPException(404, "Media not found")
    return {"ready": matting.has_matte(m), **matting.status()}


@router.post("/api/media/{mid}/bgpreview")
def background_preview(mid: str, body: BgPreview):
    """One composited frame (PNG) so the effect can be checked before it is applied to the clip."""
    import cv2

    m = media.get_row(mid)
    if m is None or m["kind"] != "video":
        raise HTTPException(404, "Video not found")
    back = None
    if body.mode in ("image", "video"):
        row = media.get_row(body.bgMediaId) if body.bgMediaId else None
        if row is None or row["status"] != "ready":
            raise HTTPException(400, "Choose an uploaded image or video to use as the new background.")
        path = str(media.render_path(row["id"]))
        if row["kind"] == "image":
            back = cv2.imread(path)
        elif row["kind"] == "video":
            cap = cv2.VideoCapture(path)
            ok, back = cap.read()
            cap.release()
            back = back if ok else None
        if back is None:
            raise HTTPException(400, f"'{row['name']}' is not a usable {body.mode}.")
    try:
        png = matting.preview_frame(m, body.t, body.model_dump(), back)
    except matting.MattingError as e:
        raise HTTPException(422, str(e))
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})
