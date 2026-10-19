"""Pydantic models for the project document and API payloads.

The edit decision list (EDL) is the single source of truth for the timeline and
for rendering. Clip and caption times are *source* times; output positions are
derived by services.editing.layout (mirrored in frontend/src/lib/layout.ts).
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

Style = Literal["dynamic", "cinematic", "vlog", "travel", "marketing", "social", "professional", "auto",
                "energetic", "minimal", "documentary"]
CaptionPresetName = Literal["classic", "bold", "karaoke", "dynamic", "cinematic"]
Aspect = Literal["16:9", "9:16", "1:1", "4:5", "original"]
Look = Literal["none", "warm", "cool", "cinematic", "vivid", "bw", "faded"]
TransitionType = Literal["fade", "fadeblack", "fadewhite", "dissolve", "wipeleft", "wiperight",
                         "slideleft", "slideright", "circleopen", "pixelize"]
Quality = Literal["draft", "standard", "high"]
Intensity = Literal["light", "balanced", "aggressive"]
DurationPreset = Literal["15", "30", "60", "90", "custom", "auto"]
MusicMood = Literal["cinematic", "energetic", "relaxing", "happy", "dramatic"]
SubtitleLanguage = Literal["auto", "en", "zh", "ms", "es", "fr", "de", "it", "pt", "ru", "ja", "ko", "hi", "ar", "id",
                           "ta", "th", "tr", "vi"]
MusicSource = Literal["none", "upload", "library", "auto"]


class AiSettings(BaseModel):
    targetDuration: Optional[float] = Field(None, ge=5, le=600)   # None = style decides
    musicId: Optional[str] = None
    musicVolume: float = Field(0.35, ge=0.02, le=1.0)
    captions: bool = False
    burnCaptions: bool = True
    removeSilence: bool = True
    sceneDetection: bool = True
    highlightDetection: bool = True
    highlightSensitivity: float = Field(0.5, ge=0.0, le=1.0)  # 0 = only top moments, 1 = keep more
    boringRemoval: bool = True  # auto-detect and remove boring/low-quality sections
    transitions: bool = True
    normalizeAudio: bool = True
    smartCrop: bool = True
    beatSync: bool = True
    resolution: Literal[720, 1080] = 720
    look: Optional[Look] = None                                  # None = style default
    intensity: Intensity = "balanced"               # light/balanced/aggressive cut aggressiveness
    instruction: str = Field("", max_length=20000)    # plain-language request, turned into a validated plan
    captionPreset: Optional[CaptionPresetName] = None  # None = the style decides
    durationPreset: Optional[DurationPreset] = None  # UI convenience; "custom"/"auto" defer to targetDuration
    musicSource: MusicSource = "none"               # "upload" uses musicId; "library"/"auto" need real tracks
    musicMood: Optional[MusicMood] = None            # only meaningful when musicSource == "auto"
    subtitleLanguage: SubtitleLanguage = "auto"      # hint passed to the transcription engine
    subtitlePreset: Literal["standard", "bold", "minimal", "social", "cinematic"] = "standard"


class BgRemoval(BaseModel):
    """AI background removal for one clip. Non-destructive: only changes what the renderer composites."""
    enabled: bool = False
    mode: Literal["color", "image", "video", "blur"] = "color"
    color: str = "#00B140"
    blur: float = Field(50, ge=0, le=100)          # blur strength for mode == "blur"
    bgMediaId: Optional[str] = None                # uploaded image/video for mode == "image" / "video"


class Keyframe(BaseModel):
    t: float = Field(ge=0)                    # seconds into the clip, on the output timeline (after speed)
    scale: float = Field(1.0, ge=0.1, le=5)
    x: float = Field(0.0, ge=-1, le=1)        # offset as a fraction of the frame width
    y: float = Field(0.0, ge=-1, le=1)
    rotation: float = Field(0.0, ge=-360, le=360)
    opacity: float = Field(1.0, ge=0, le=1)
    ease: Literal["linear", "smooth"] = "linear"   # shape of the move to the next keyframe


class ClipEffect(BaseModel):
    id: str
    amount: float = Field(0.5, ge=0, le=1)


class ClipFilter(BaseModel):
    id: str
    strength: float = Field(1.0, ge=0, le=1)


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
    scoreBreakdown: Optional[dict] = None  # per-feature scores {motion, audio, sharp, face, ...}
    rejected: bool = False                 # user rejected this highlight suggestion
    boring: bool = False                   # auto-detected as low-quality / boring section
    boringReason: Optional[str] = None     # why: "low_motion", "silent", "blurry", "static", "low_energy"
    bgRemoval: Optional[BgRemoval] = None  # AI background removal / replacement
    speed: float = Field(1.0, ge=0.25, le=4)   # playback speed of this clip (1 = normal)
    freeze: Optional[float] = Field(None, ge=0.1, le=30)  # freeze frame: srcStart's frame held for this many seconds
    keyframes: List[Keyframe] = Field(default_factory=list)  # animation of scale/position/rotation/opacity
    effects: List[ClipEffect] = Field(default_factory=list)  # video effects (blur, glitch, ...), applied in order
    filter: Optional[ClipFilter] = None                      # colour filter for this clip, on top of the project grade
    transitionType: Optional[str] = None                     # overrides the project transition leading into this clip
    volume: float = Field(1.0, ge=0, le=2)                   # level of this clip's own sound
    audioEffect: Literal["none", "denoise", "voice", "deep", "chipmunk", "robot", "echo", "radio"] = "none"


class CaptionWord(BaseModel):
    word: str
    start: float
    end: float


class Caption(BaseModel):
    id: str
    mediaId: str
    srcStart: float
    srcEnd: float
    text: str
    words: Optional[List[CaptionWord]] = None  # word-level timing for karaoke highlight
    manual: bool = False                       # timing moved by hand; the transcript's own times are kept below
    origStart: Optional[float] = None          # the transcript's own start/end, kept so manual timing can be reset
    origEnd: Optional[float] = None
    wordShift: float = 0                       # how far the words were moved along with a manual move


class CaptionStyle(BaseModel):
    fontSize: Literal["small", "medium", "large"] = "medium"
    position: Literal["top", "center", "bottom"] = "bottom"
    color: str = "#FFFFFF"
    background: Literal["box", "outline", "none"] = "box"
    highlightColor: str = "#FFD700"  # word highlight colour (karaoke mode)
    outlineColor: str = "#000000"
    uppercase: bool = False
    preset: Literal["classic", "bold", "karaoke", "dynamic", "cinematic", "custom"] = "classic"
    karaoke: bool = False             # highlight each word while it is spoken (needs word timestamps)
    animation: Literal["none", "fade", "pop", "scale"] = "none"


FontFamily = Literal["Arial", "Georgia", "Times New Roman", "Courier New", "Trebuchet MS", "Comic Sans MS", "Impact"]


class Title(BaseModel):
    """A text overlay. x/y/size are fractions of the VIDEO frame (centre of the text, and its height), so the
    preview and the exported MP4 place it identically at any resolution."""
    id: str
    text: str
    start: float = Field(0, ge=0)
    duration: float = Field(3, gt=0, le=60)
    position: Literal["top", "center", "bottom"] = "center"   # preset used until x/y is set
    x: float = Field(0.5, ge=-0.2, le=1.2)
    y: Optional[float] = Field(None, ge=-0.2, le=1.2)          # None: derived from `position`
    size: float = Field(0.07, ge=0.015, le=0.5)               # text height as a fraction of frame height
    rotation: float = Field(0, ge=-180, le=180)               # degrees, clockwise
    font: FontFamily = "Arial"
    weight: Literal["normal", "bold"] = "bold"
    color: str = "#FFFFFF"
    opacity: float = Field(1.0, ge=0, le=1)
    align: Literal["left", "center", "right"] = "center"
    strokeColor: str = "#000000"
    strokeWidth: float = Field(0.0, ge=0, le=0.3)             # fraction of the text size
    shadow: bool = False
    background: str = "#000000"                               # "" = no background box
    backgroundOpacity: float = Field(0.65, ge=0, le=1)
    animation: Literal["none", "fade", "pop", "scale", "slide"] = "none"


class Transition(BaseModel):
    type: TransitionType = "fade"
    duration: float = Field(0.5, ge=0.1, le=3.0)


class Music(BaseModel):
    mediaId: str
    volume: float = Field(0.35, ge=0.02, le=1.0)
    duck: bool = True


class AudioClip(BaseModel):
    """A clip on the audio timeline (music or an added sound). Never alters the source file: the renderer reads
    [trimIn, trimIn + duration] of the source and places it at `start` on the output timeline."""
    id: str
    mediaId: str                                   # uploaded audio media id, or a bundled library id ("lib:...")
    kind: Literal["music", "audio"] = "music"
    start: float = Field(0, ge=0)                  # position on the output timeline, seconds
    trimIn: float = Field(0, ge=0)                 # in-point inside the source, seconds
    duration: Optional[float] = Field(None, gt=0)  # visible length; None = to the end of the video
    volume: float = Field(0.35, ge=0.0, le=1.0)
    fadeIn: float = Field(0, ge=0, le=30)
    fadeOut: float = Field(0, ge=0, le=30)
    loop: bool = False                             # repeat the trimmed source to fill `duration`
    duck: bool = True                              # lower under speech
    effect: Optional[Literal["none", "denoise", "voice", "deep", "chipmunk", "robot", "echo", "radio"]] = "none"


class AudioMaster(BaseModel):
    normalize: bool = True
    lufs: float = Field(-14, ge=-30, le=-9)
    clean: bool = False
    fades: bool = False


class RemovedSegment(BaseModel):
    mediaId: str
    start: float
    end: float
    reason: str
    label: str = ""


class ExcludedMedia(BaseModel):
    mediaId: str
    name: str = ""
    reason: str = ""


class Edl(BaseModel):
    version: int = 1
    style: Style = "dynamic"
    aspect: Aspect = "16:9"
    fit: Literal["crop", "blur"] = "crop"
    clips: List[EdlClip] = []
    transition: Optional[Transition] = None
    look: Look = "none"
    music: Optional[Music] = None            # mirror of the first music clip (kept for older projects and the AI panel)
    audioClips: List[AudioClip] = []         # the audio timeline: the source of truth once present
    markers: List[float] = []                # timeline markers (seconds), snapping targets
    captions: List[Caption] = []
    captionStyle: CaptionStyle = CaptionStyle()
    burnCaptions: bool = True
    titles: List[Title] = []
    audio: AudioMaster = AudioMaster()
    beat: Optional[float] = None      # seconds per beat when cuts were beat-synced
    notes: List[str] = []
    videoType: Optional[str] = None       # auto-detected: "action", "talking_head", "scenic", "mixed"
    resolvedStyle: Optional[str] = None   # when style == "auto", which concrete style was actually used
    plan: Optional[dict] = None            # what the AI understood from the instruction (chips, warnings)
    conflict: Optional[dict] = None        # requested target length could not fit every video: requested/suggested
    template: Optional[dict] = None        # applied template: id, name and the sections it laid out
    @model_validator(mode="after")
    def _sync_music(self):
        """audioClips is the truth. Older projects only have `music`: migrate it (it looped before, so keep that)."""
        if not self.audioClips and self.music:
            self.audioClips = [AudioClip(id="a0", mediaId=self.music.mediaId, kind="music", volume=self.music.volume,
                                         duck=self.music.duck, loop=True)]
        first = next((c for c in self.audioClips if c.kind == "music"), None)
        self.music = Music(mediaId=first.mediaId, volume=first.volume, duck=first.duck) if first else None
        return self

    removed: List[RemovedSegment] = []     # source ranges the AI cut out, with the reason
    excluded: List[ExcludedMedia] = []     # videos left out entirely (only when nothing usable), with the reason


class ExportSettings(BaseModel):
    filename: str = "frameflow-export"
    resolution: Literal[720, 1080, 2160] = 1080
    fps: Literal[24, 30, 60] = 30
    quality: Quality = "standard"
    subtitleHandling: Literal["burn", "srt", "none"] = "burn"


class ProjectDoc(BaseModel):
    template: Optional[str] = None         # optional structural template id (see services/templates.py)
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
