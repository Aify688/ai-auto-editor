export type Style = "dynamic" | "cinematic" | "vlog";
export type Aspect = "16:9" | "9:16" | "1:1";
export type Look = "none" | "warm" | "cool" | "cinematic" | "vivid" | "bw" | "faded";
export type Quality = "draft" | "standard" | "high";
export type NavKey = "media" | "ai" | "audio" | "text" | "captions" | "effects" | "templates";

export interface AiSettings {
  targetDuration: number | null;
  musicId: string | null;
  musicVolume: number;
  captions: boolean;
  burnCaptions: boolean;
  removeSilence: boolean;
  sceneDetection: boolean;
  highlightDetection: boolean;
  transitions: boolean;
  normalizeAudio: boolean;
  smartCrop: boolean;
  beatSync: boolean;
  resolution: 720 | 1080;
  look: Look | null;
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
}

export interface Caption {
  id: string;
  mediaId: string;
  srcStart: number;
  srcEnd: number;
  text: string;
}

export interface Title {
  id: string;
  text: string;
  start: number;
  duration: number;
  position: "top" | "center" | "bottom";
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
  captions: Caption[];
  burnCaptions: boolean;
  titles: Title[];
  audio: { normalize: boolean; lufs: number; clean: boolean; fades: boolean };
  beat: number | null;
  notes: string[];
}

export interface ExportSettings {
  filename: string;
  resolution: 720 | 1080;
  fps: 24 | 25 | 30 | 60;
  quality: Quality;
}

export interface ProjectDoc {
  style: Style;
  aspect: Aspect;
  settings: AiSettings;
  edl: Edl | null;
  export: ExportSettings;
}

export interface RenderInfo {
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
  kind: "ingest" | "generate" | "render" | "export" | "transcribe";
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

export interface SystemStatus {
  ffmpeg: { ok: boolean; version: string | null; hint: string | null };
  sceneDetection: { ok: boolean; engine: string; hint: string };
  transcription: { ok: boolean; engine: string; modelCached: boolean; hint: string | null };
  transitions: { ok: boolean };
  musicDucking: { ok: boolean };
  limits: { maxUploadMb: number; extensions: string[] };
  dataDir: string;
}
