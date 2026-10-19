export type Style =
  | "dynamic" | "cinematic" | "vlog" | "travel" | "marketing" | "social" | "professional" | "auto"
  | "energetic" | "minimal" | "documentary";
export type Aspect = "16:9" | "9:16" | "1:1" | "4:5" | "original";
export type Look = "none" | "warm" | "cool" | "cinematic" | "vivid" | "bw" | "faded";
export type Quality = "draft" | "standard" | "high";
export type NavKey = "media" | "ai" | "audio" | "text" | "captions" | "effects" | "templates";
export type Intensity = "light" | "balanced" | "aggressive";
export type DurationPreset = "15" | "30" | "60" | "90" | "custom" | "auto";
export type MusicMood = "cinematic" | "energetic" | "relaxing" | "happy" | "dramatic";
export type MusicSource = "none" | "upload" | "library" | "auto";
export type SubtitleLanguage =
  | "auto" | "en" | "zh" | "ms" | "es" | "fr" | "de" | "it" | "pt" | "ru" | "ja" | "ko" | "hi" | "ar" | "id" | "ta" | "th" | "tr" | "vi";
export type SubtitlePreset = "standard" | "bold" | "minimal" | "social" | "cinematic";

export interface AiSettings {
  targetDuration: number | null;
  musicId: string | null;
  musicVolume: number;
  captions: boolean;
  burnCaptions: boolean;
  removeSilence: boolean;
  removeFillers?: boolean;
  sceneDetection: boolean;
  highlightDetection: boolean;
  highlightSensitivity: number;
  boringRemoval: boolean;
  transitions: boolean;
  normalizeAudio: boolean;
  smartCrop: boolean;
  beatSync: boolean;
  resolution: 720 | 1080;
  look: Look | null;
  intensity: Intensity;
  instruction: string;
  captionPreset: "classic" | "bold" | "karaoke" | "dynamic" | "cinematic" | null;
  durationPreset: DurationPreset | null;
  musicSource: MusicSource;
  musicMood: MusicMood | null;
  subtitleLanguage: SubtitleLanguage;
  subtitlePreset: SubtitlePreset;
}

export interface EdlClip {
  id: string;
  mediaId: string;
  srcStart: number;
  srcEnd: number;
  sceneBreak: boolean;
  label: string;
  focusX: number;
  focusY: number;
  score: number | null;
  scoreBreakdown: Record<string, number> | null;
  rejected: boolean;
  boring: boolean;
  boringReason: string | null;
  bgRemoval?: BgRemoval | null;
  /** Playback speed of this clip (1 = normal). */
  speed?: number;
  /** Freeze frame: the frame at srcStart is held for this many seconds. */
  freeze?: number | null;
  /** Animation of scale/position/rotation/opacity; times are seconds into the clip on the output timeline. */
  keyframes?: Keyframe[];
  /** Video effects (blur, glitch, ...) applied in order. */
  effects?: ClipEffect[];
  /** Colour filter for this clip, on top of the project grade. */
  filter?: ClipFilter | null;
  /** Overrides the project transition leading into this clip. */
  transitionType?: string | null;
  /** This clip's own sound: level (1 = original, up to 2) and a voice/sound effect. */
  volume?: number;
  audioEffect?: AudioEffect;
}

export type AudioEffect = "none" | "denoise" | "voice" | "deep" | "chipmunk" | "robot" | "echo" | "radio";

export interface ClipEffect {
  id: string;
  amount: number;
}

export interface ClipFilter {
  id: string;
  strength: number;
}

export interface Keyframe {
  t: number;
  scale: number;
  /** Offsets as a fraction of the frame (0 = centred). */
  x: number;
  y: number;
  rotation: number;
  opacity: number;
  /** Shape of the move to the next keyframe. */
  ease?: "linear" | "smooth";
}

export type BgMode = "color" | "image" | "video" | "blur";

/** AI background removal for one clip (non-destructive: the renderer composites it). */
export interface BgRemoval {
  enabled: boolean;
  mode: BgMode;
  color: string;
  blur: number;
  bgMediaId: string | null;
}

export interface CaptionWord {
  word: string;
  start: number;
  end: number;
}

export interface Caption {
  id: string;
  mediaId: string;
  srcStart: number;
  srcEnd: number;
  text: string;
  words?: CaptionWord[] | null;
  /** Timing was changed by hand. origStart/origEnd are the transcript's own times (for Reset). */
  manual?: boolean;
  origStart?: number | null;
  origEnd?: number | null;
  wordShift?: number;
}

/** A clip on the audio timeline. Source files are never modified: start/trim/duration/fades are render instructions. */
export interface AudioClip {
  id: string;
  mediaId: string;
  kind: "music" | "audio";
  start: number;
  trimIn: number;
  duration: number | null;
  volume: number;
  fadeIn: number;
  fadeOut: number;
  loop: boolean;
  duck: boolean;
  effect?: AudioEffect;
}

export type CaptionFontSize = "small" | "medium" | "large";
export type CaptionPosition = "top" | "center" | "bottom";
export type CaptionBackground = "box" | "outline" | "none";

export interface CaptionStyle {
  fontSize: CaptionFontSize;
  position: CaptionPosition;
  color: string;
  background: CaptionBackground;
  highlightColor: string;
  outlineColor?: string;
  uppercase: boolean;
  preset?: CaptionPreset;
  karaoke?: boolean;
  animation?: CaptionAnimation;
}

export type CaptionPreset = "classic" | "bold" | "karaoke" | "dynamic" | "cinematic" | "custom";
export type CaptionAnimation = "none" | "fade" | "pop" | "scale";

export type TextAnimation = "none" | "fade" | "pop" | "scale" | "slide";
export type FontFamily = "Arial" | "Georgia" | "Times New Roman" | "Courier New" | "Trebuchet MS" | "Comic Sans MS" | "Impact";

/** A text overlay. x, y and size are fractions of the video frame, so preview and export agree at any resolution. */
export interface Title {
  id: string;
  text: string;
  start: number;
  duration: number;
  position: "top" | "center" | "bottom";
  x?: number;
  y?: number | null;
  size?: number;
  rotation?: number;
  font?: FontFamily;
  weight?: "normal" | "bold";
  color?: string;
  opacity?: number;
  align?: "left" | "center" | "right";
  strokeColor?: string;
  strokeWidth?: number;
  shadow?: boolean;
  background?: string;
  backgroundOpacity?: number;
  animation?: TextAnimation;
}

export interface Edl {
  version: number;
  style: Style;
  aspect: Aspect;
  fit: "crop" | "blur";
  clips: EdlClip[];
  transition: { type: string; duration: number } | null;
  look: Look;
  music: { mediaId: string; volume: number; duck: boolean } | null;
  audioClips: AudioClip[];
  markers: number[];
  captions: Caption[];
  captionStyle: CaptionStyle;
  burnCaptions: boolean;
  titles: Title[];
  audio: { normalize: boolean; lufs: number; clean: boolean; fades: boolean };
  beat: number | null;
  notes: string[];
  videoType: string | null;
  /** What the AI understood from the instruction (chips and warnings). */
  plan?: { instruction: string; understood: string[]; warnings: string[] } | null;
  /** The requested length could not hold every video. */
  conflict?: { requested: number; suggested: number; videos: number; message: string } | null;
  template?: { id: string; name: string; sections: { name: string; start: number; end: number }[] } | null;
  resolvedStyle: Style | null;
  /** Source ranges the AI cut out, with the reason (silence, blank frames, ...). */
  removed?: RemovedSegment[];
  /** Videos left out entirely; only when nothing usable was found in them. */
  excluded?: { mediaId: string; name: string; reason: string }[];
}

export interface RemovedSegment {
  mediaId: string;
  start: number;
  end: number;
  reason: string;
  label: string;
}

export interface ExportSettings {
  filename: string;
  resolution: 720 | 1080 | 2160;
  fps: 24 | 30 | 60;
  quality: Quality;
  subtitleHandling: "burn" | "srt" | "none";
}

export interface ProjectDoc {
  template?: string | null;
  style: Style;
  aspect: Aspect;
  settings: AiSettings;
  edl: Edl | null;
  export: ExportSettings;
}

export interface RenderInfo {
  id: string;
  url: string;
  duration: number;
  width: number;
  height: number;
  edl: Edl;
  jobId: string;
  createdAt: number;
}

export interface Project {
  id: string;
  name: string;
  doc: ProjectDoc;
  render: RenderInfo | null;
  /** Past generated versions, most recent first; capped server-side. Regenerating never destroys these. */
  history: RenderInfo[];
  createdAt: number;
  updatedAt: number;
}

export interface ProjectSummary {
  id: string;
  name: string;
  createdAt: number;
  updatedAt: number;
  mediaCount: number;
  coverUrl: string | null;
  hasRender: boolean;
  renderDuration: number | null;
}

export interface SpriteInfo {
  step: number;
  count: number;
  tileW: number;
  tileH: number;
}

export interface MediaInfo {
  url?: string;
  thumbUrl?: string;
  proxyUrl?: string;
  spriteUrl?: string;
  sprite?: SpriteInfo;
  peaksUrl?: string;
  peakStep?: number;
  videoCodec?: string;
  audioCodec?: string;
  bitrate?: number;
}

export interface Media {
  id: string;
  projectId: string;
  name: string;
  kind: "video" | "image" | "audio";
  ext: string;
  size: number;
  status: "processing" | "ready" | "error";
  error: string | null;
  position: number;
  duration: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  hasAudio: boolean;
  info: MediaInfo;
}

export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export interface Job {
  id: string;
  projectId: string;
  kind: "ingest" | "generate" | "textvideo" | "render" | "export" | "transcribe" | "matte";
  status: JobStatus;
  stage: string | null;
  progress: number;
  message: string | null;
  error: string | null;
  params: Record<string, unknown>;
  result: Record<string, any> | null;
  stages: { key: string; label: string }[];
  createdAt: number;
  updatedAt: number;
}

export interface MusicLibraryTrack {
  id: string;
  mood: MusicMood;
  title: string;
  duration: number;
  attribution: string;
  url: string;
}

export interface TemplateDef {
  id: string;
  name: string;
  description: string;
  duration: number;
  aspect: Aspect;
  suggestedStyle: Style;
  mood: MusicMood;
  sections: { name: string; weight: number; text: string }[];
}

export interface MusicRecommendation extends MusicLibraryTrack {
  tempo: number;
  score: number;
  reason: string;
  suggestedVolume: number;
}

export interface MusicRecommendations {
  /** "style": the footage has not been analysed yet, so only the editing style was used. */
  basis: "footage" | "style";
  style: string;
  profile: Record<string, number>;
  license: string;
  attribution: string;
  tracks: MusicRecommendation[];
}

export interface InstructionPlan {
  understood: string[];
  warnings: string[];
  style: Style | null;
  aspect: Aspect | null;
  template: string | null;
  settings: Record<string, unknown>;
}

export interface GenerationPlan {
  mode: "edit" | "text" | "none";
  sceneCount?: number;
  seconds?: number;
  chars?: number;
  notes?: string[];
  error?: string;
}

export interface SystemStatus {
  ffmpeg: { ok: boolean; version: string | null; hint: string | null };
  sceneDetection: { ok: boolean; engine: string; hint: string };
  transcription: { ok: boolean; engine: string; modelCached: boolean; hint: string | null };
  textToVideo?: { configured: boolean; provider: string; model: string; clipSeconds: number; maxScenes: number; promptLimit: number; maxSeconds: number; hint: string | null };
  backgroundRemoval?: { ok: boolean; engine: string; modelCached: boolean; downloadMb?: number; license?: string; hint: string | null };
  transitions: { ok: boolean };
  musicDucking: { ok: boolean };
  limits: { maxUploadMb: number; extensions: string[] };
  dataDir: string;
  server?: { stale: boolean };
}
