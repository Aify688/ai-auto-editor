from typing import List, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..schemas import ProjectCreate, ProjectUpdate
from ..services import analysis, instructions, music_reco, projects, rendering, templates


class RestoreVersion(BaseModel):
    id: str

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _get_or_404(pid: str) -> dict:
    try:
        return projects.get(pid)
    except projects.NotFound as e:
        raise HTTPException(404, str(e))


@router.get("")
def list_projects():
    return projects.list_all()


@router.post("", status_code=201)
def create_project(body: ProjectCreate):
    return projects.create(body.name)


@router.get("/{pid}")
def get_project(pid: str):
    return _get_or_404(pid)


@router.put("/{pid}")
def update_project(pid: str, body: ProjectUpdate):
    _get_or_404(pid)
    return projects.update(pid, name=body.name, doc=body.doc)


@router.delete("/{pid}", status_code=204)
def delete_project(pid: str):
    _get_or_404(pid)
    projects.delete(pid)


@router.post("/{pid}/render/restore")
def restore_render(pid: str, body: RestoreVersion):
    """Make a previously-generated version current again without losing the one it replaces."""
    _get_or_404(pid)
    try:
        projects.restore_render(pid, body.id)
    except projects.NotFound as e:
        raise HTTPException(404, str(e))
    return projects.get(pid)


@router.get("/{pid}/captions.{fmt}")
def download_captions(pid: str, fmt: str):
    """SRT / WebVTT of the project's current captions, timed against the current timeline."""
    if fmt not in ("srt", "vtt"):
        raise HTTPException(404, "Use captions.srt or captions.vtt")
    project = _get_or_404(pid)
    edl = (project.get("doc") or {}).get("edl")
    text = rendering.build_subtitle_text(edl, fmt) if edl else None
    if not text:
        raise HTTPException(404, "There are no captions on the timeline yet. Generate captions first.")
    name = rendering.safe_filename(project.get("name") or "captions")
    media_type = "text/vtt" if fmt == "vtt" else "application/x-subrip"
    return Response(text, media_type=media_type + "; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})


class PlanRequest(BaseModel):
    instruction: str = ""


@router.post("/plan")
def preview_plan(body: PlanRequest):
    """What the AI understood from a plain-language request, before anything is generated or changed."""
    return instructions.parse(body.instruction)


class MusicTrackOut(BaseModel):
    id: str
    mood: str
    title: str
    duration: float
    attribution: str
    url: str
    tempo: float
    score: float
    reason: str
    suggestedVolume: float


class MusicRecommendationsOut(BaseModel):
    basis: Literal["footage", "style"]   # "style": the footage has not been analysed yet, so only the style was used
    style: str
    profile: dict
    license: str
    attribution: str
    tracks: List[MusicTrackOut]


@router.get("/{pid}/music-recommendations", response_model=MusicRecommendationsOut)
def music_recommendations(pid: str):
    """Three licensed library tracks that suit this project, each with a short reason. Always JSON."""
    project = _get_or_404(pid)
    doc = project["doc"]
    rows = [m for m in analysis.media_rows(pid, ("video", "image")) if m["status"] == "ready"]
    if not rows:
        raise HTTPException(409, "Upload a video first, then music can be matched to it.")
    settings = doc.get("settings") or {}
    style = doc.get("style") if doc.get("style") not in (None, "auto") else ((doc.get("edl") or {}).get("resolvedStyle") or "cinematic")
    hint = settings.get("musicMood")
    if not hint and settings.get("instruction"):
        hint = (instructions.parse(settings["instruction"])["settings"]).get("musicMood")
    data, basis = {}, "footage"
    try:
        for m in rows:
            vis = analysis.cached_only(m, "features")
            aud = analysis.cached_only(m, "audio") if m["kind"] == "video" else {"silences": [], "energy": [], "step": 0.5}
            sc = analysis.cached_only(m, "scenes") if m["kind"] == "video" else {"scenes": [[0, 1]]}
            data[m["id"]] = {"visual": vis, "audio": aud, "scenes": sc["scenes"]}
        profile = music_reco.footage_profile(rows, data)
    except analysis.AnalysisError:
        basis, profile = "style", music_reco.style_profile(rows, style)
    from ..services import music_library
    return {"basis": basis, "style": style, "profile": profile, "license": "CC BY 4.0", "attribution": music_library.ATTRIBUTION,
            "tracks": music_reco.recommend(profile, style, hint)}


router_templates = APIRouter(prefix="/api/templates", tags=["templates"])


@router_templates.get("")
def list_templates():
    return templates.list_all()
