from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import music_library, preferences, system, tts

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("")
def get_status():
    return system.status()


@router.get("/fonts")
def get_fonts():
    """Font families that can be rendered into the exported video on this machine."""
    from video_editor.overlay import available_fonts
    return available_fonts()


@router.get("/music-library")
def get_music_library():
    """Real, CC-BY-licensed background tracks available for musicSource 'library'/'auto'.
    See backend/assets/music/CREDITS.md for full attribution."""
    return music_library.list_library()


@router.get("/tts-voices")
def get_tts_voices():
    """Voices for text to speech, with an honest status when no engine is installed."""
    return tts.status()


class PreferencesPatch(BaseModel):
    whisperModel: Optional[str] = None


@router.get("/preferences")
def get_preferences():
    return {**preferences.get(), "whisperCached": {m["id"]: system.whisper_model_cached(m["id"]) for m in preferences.get()["whisperModels"]}}


@router.put("/preferences")
def put_preferences(body: PreferencesPatch):
    try:
        preferences.update(body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return get_preferences()
