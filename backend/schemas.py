"""Pydantic models for the project document and API payloads.

The edit decision list (EDL) is the single source of truth for the timeline and
for rendering. Clip and caption times are *source* times; output positions are
derived by services.editing.layout (mirrored in frontend/src/lib/layout.ts).
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Style = Literal["dynamic", "cinematic", "vlog"]
Aspect = Literal["16:9", "9:16", "1:1"]
Look = Literal["none", "warm", "cool", "cinematic", "vivid", "bw", "faded"]
TransitionType = Literal["fade", "fadeblack", "fadewhite", "dissolve", "wipeleft", "wiperight",
                         "slideleft", "slideright", "circleopen", "pixelize"]
Quality = Literal["draft", "standard", "high"]


class AiSettings(BaseModel):
    targetDuration: Optional[float] = Field(None, ge=5, le=600)   # None = style decides
    musicId: Optional[str] = None
    musicVolume: float = Field(0.35, ge=0.02, le=1.0)
    captions: bool = False
    burnCaptions: bool = True
    removeSilence: bool = True
    sceneDetection: bool = True
    highlightDetection: bool = True
    transitions: bool = True
    normalizeAudio: bool = True
    smartCrop: bool = True
    beatSync: bool = True
    resolution: Literal[720, 1080] = 720
    look: Optional[Look] = None                                  # None = style default


class EdlClip(BaseModel):
    id: str
    mediaId: str
    srcStart: float = Field(ge=0)
    srcEnd: float = Field(gt=0)
    sceneBreak: bool = True       # transition (if any) precedes this clip
    label: str = ""
    focusX: float = Field(0.5, ge=0, le=1)   # subject position in the source frame (smart crop)
    focusY: float = Field(0.5, ge=0, le=1)
    score: Optional[float] = None


class Caption(BaseModel):
    id: str
    mediaId: str
    srcStart: float
    srcEnd: float
    text: str


class Title(BaseModel):
    id: str
    text: str
    start: float = Field(0, ge=0)
    duration: float = Field(3, gt=0, le=60)
    position: Literal["top", "center", "bottom"] = "center"


class Transition(BaseModel):
    type: TransitionType = "fade"
    duration: float = Field(0.5, ge=0.1, le=3.0)


class Music(BaseModel):
    mediaId: str
    volume: float = Field(0.35, ge=0.02, le=1.0)
    duck: bool = True


class AudioMaster(BaseModel):
    normalize: bool = True
    lufs: float = Field(-14, ge=-30, le=-9)
    clean: bool = False
    fades: bool = False


class Edl(BaseModel):
    version: int = 1
    style: Style = "dynamic"
    aspect: Aspect = "16:9"
    fit: Literal["crop", "blur"] = "crop"
    clips: List[EdlClip] = []
    transition: Optional[Transition] = None
    look: Look = "none"
    music: Optional[Music] = None
    captions: List[Caption] = []
    burnCaptions: bool = True
    titles: List[Title] = []
    audio: AudioMaster = AudioMaster()
    beat: Optional[float] = None      # seconds per beat when cuts were beat-synced
    notes: List[str] = []


class ExportSettings(BaseModel):
    filename: str = "frameflow-export"
    resolution: Literal[720, 1080] = 1080
    fps: Literal[24, 25, 30, 60] = 30
    quality: Quality = "standard"


class ProjectDoc(BaseModel):
    style: Style = "dynamic"
    aspect: Aspect = "16:9"
    settings: AiSettings = AiSettings()
    edl: Optional[Edl] = None
    export: ExportSettings = ExportSettings()


class ProjectCreate(BaseModel):
    name: str = Field("Untitled project", min_length=1, max_length=120)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    doc: Optional[ProjectDoc] = None


class MediaOrder(BaseModel):
    ids: List[str]


class GenerateRequest(BaseModel):
    doc: ProjectDoc


class ExportRequest(BaseModel):
    doc: ProjectDoc
