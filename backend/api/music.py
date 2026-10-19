import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services import music_search, projects
from ..workers import jobs

router = APIRouter(tags=["music"])


@router.get("/api/music/status")
def music_status():
    return music_search.status()


@router.get("/api/music/search")
async def music_find(q: str = Query("", max_length=120), restricted: bool = False):
    """Search the bundled library and (when configured) Jamendo by title, artist, genre or mood."""
    return await run_in_threadpool(music_search.search, q, restricted)


@router.get("/api/music/preview/{track_id}")
async def music_preview(track_id: str):
    """Stream a provider track for listening. The provider's URL and client id never reach the browser."""
    try:
        src = await run_in_threadpool(music_search.preview_source, track_id)
        upstream = await run_in_threadpool(urllib.request.urlopen, urllib.request.Request(src), None, 30)
    except music_search.MusicError as e:
        raise HTTPException(404, str(e))
    except (urllib.error.URLError, TimeoutError, OSError):
        raise HTTPException(502, "The music provider could not be reached.")

    def chunks():
        try:
            while True:
                b = upstream.read(1 << 16)
                if not b:
                    break
                yield b
        finally:
            upstream.close()

    return StreamingResponse(chunks(), media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=3600"})


class AddTrack(BaseModel):
    trackId: str = Field(min_length=3, max_length=80)


@router.post("/api/projects/{pid}/music/add", status_code=201)
async def music_add(pid: str, body: AddTrack):
    """Make a chosen track part of the project (downloads provider tracks into Media). Placing it on the timeline is the
    client's job, after this succeeds."""
    try:
        projects.get(pid)
    except projects.NotFound as e:
        raise HTTPException(404, str(e))
    try:
        res = await run_in_threadpool(music_search.add_to_project, pid, body.trackId)
    except music_search.MusicError as e:
        raise HTTPException(422, str(e))
    if res["media"]:
        jobs.submit("ingest", pid, {"mediaId": res["mediaId"]})
    return res
