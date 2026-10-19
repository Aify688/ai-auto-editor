// Style metadata. Rendering parameters mirror backend/services/editing.py STYLES.
import type { AiSettings, Aspect, CaptionStyle, Edl, Look, ProjectDoc, Style } from "../types";

export interface StyleInfo {
  key: Style;
  name: string;
  traits: string[];
  bestFor: string;
  transition: { type: string; duration: number };
  look: Look;
  lufs: number;
  clean: boolean;
  fades: boolean;
  /** Toggles that suit the style; applied when the style is picked (still editable). */
  defaults: Partial<AiSettings>;
}

export const STYLES: Record<Style, StyleInfo> = {
  dynamic: {
    key: "dynamic",
    name: "Dynamic",
    traits: ["Fast cuts", "Beat sync", "High energy"],
    bestFor: "Social media",
    transition: { type: "fadewhite", duration: 0.2 },
    look: "vivid",
    lufs: -14,
    clean: false,
    fades: false,
    defaults: { removeSilence: false, beatSync: true, captions: false, highlightSensitivity: 0.5, boringRemoval: true },
  },
  cinematic: {
    key: "cinematic",
    name: "Cinematic",
    traits: ["Smooth fades", "Slow pacing", "Film grade"],
    bestFor: "Travel & story",
    transition: { type: "fade", duration: 1.0 },
    look: "cinematic",
    lufs: -16,
    clean: false,
    fades: true,
    defaults: { removeSilence: false, captions: false, highlightSensitivity: 0.5, boringRemoval: true },
  },
  vlog: {
    key: "vlog",
    name: "Vlog",
    traits: ["Natural cuts", "Clear speech", "Light fades"],
    bestFor: "Everyday videos",
    transition: { type: "fade", duration: 0.35 },
    look: "warm",
    lufs: -16,
    clean: true,
    fades: false,
    defaults: { removeSilence: true, captions: true, highlightSensitivity: 0.5, boringRemoval: true },
  },
  travel: {
    key: "travel",
    name: "Travel",
    traits: ["Scenic pacing", "Dissolves", "Vivid color"],
    bestFor: "Travel & adventure",
    transition: { type: "dissolve", duration: 0.6 },
    look: "vivid",
    lufs: -15,
    clean: false,
    fades: true,
    defaults: { removeSilence: false, captions: false, highlightSensitivity: 0.5, boringRemoval: true },
  },
  marketing: {
    key: "marketing",
    name: "Marketing",
    traits: ["Punchy hook", "Fast cuts", "Bold color"],
    bestFor: "Ads & promos",
    transition: { type: "fadewhite", duration: 0.15 },
    look: "vivid",
    lufs: -13,
    clean: false,
    fades: false,
    defaults: { removeSilence: false, captions: true, highlightSensitivity: 0.3, boringRemoval: true },
  },
  social: {
    key: "social",
    name: "Social Media",
    traits: ["Snappy", "Short-form", "Caption-first"],
    bestFor: "Reels, TikTok, Shorts",
    transition: { type: "fadewhite", duration: 0.12 },
    look: "vivid",
    lufs: -13,
    clean: false,
    fades: false,
    defaults: { removeSilence: true, captions: true, highlightSensitivity: 0.3, boringRemoval: true },
  },
  professional: {
    key: "professional",
    name: "Professional",
    traits: ["Clean audio", "Measured pacing", "Minimal grade"],
    bestFor: "Corporate & presentations",
    transition: { type: "fade", duration: 0.6 },
    look: "none",
    lufs: -16,
    clean: true,
    fades: true,
    defaults: { removeSilence: true, captions: false, highlightSensitivity: 0.5, boringRemoval: true },
  },
  energetic: {
    key: "energetic",
    name: "Energetic",
    traits: ["Fast cuts", "Beat sync", "Bold color"],
    bestFor: "Reels, sports, hype",
    transition: { type: "fadewhite", duration: 0.18 },
    look: "vivid",
    lufs: -14,
    clean: false,
    fades: false,
    defaults: { removeSilence: false, beatSync: true, highlightSensitivity: 0.5, boringRemoval: true },
  },
  minimal: {
    key: "minimal",
    name: "Minimal",
    traits: ["Calm pacing", "Soft fades", "Natural color"],
    bestFor: "Clean, understated edits",
    transition: { type: "fade", duration: 0.5 },
    look: "none",
    lufs: -16,
    clean: false,
    fades: true,
    defaults: { removeSilence: false, captions: false, highlightSensitivity: 0.5, boringRemoval: true },
  },
  documentary: {
    key: "documentary",
    name: "Documentary",
    traits: ["Longer takes", "Clean speech", "Muted color"],
    bestFor: "Stories & interviews",
    transition: { type: "fade", duration: 0.6 },
    look: "faded",
    lufs: -16,
    clean: true,
    fades: true,
    defaults: { removeSilence: true, captions: true, highlightSensitivity: 0.5, boringRemoval: true },
  },
  auto: {
    key: "auto",
    name: "Auto",
    traits: ["Detects content type", "Picks a style for you"],
    bestFor: "Not sure which style to use",
    transition: { type: "fade", duration: 0.4 },
    look: "none",
    lufs: -15,
    clean: false,
    fades: false,
    defaults: { highlightSensitivity: 0.5, boringRemoval: true },
  },
};

export const ASPECTS: { value: Aspect; label: string; hint: string }[] = [
  { value: "16:9", label: "16:9", hint: "Landscape" },
  { value: "9:16", label: "9:16", hint: "Portrait" },
  { value: "1:1", label: "1:1", hint: "Square" },
  { value: "4:5", label: "4:5", hint: "Portrait (feed)" },
  { value: "original", label: "Original", hint: "Keep source ratio" },
];

export const DURATION_PRESETS: { value: AiSettings["durationPreset"] & string; label: string; seconds: number | null }[] = [
  { value: "15", label: "15s", seconds: 15 },
  { value: "30", label: "30s", seconds: 30 },
  { value: "60", label: "60s", seconds: 60 },
  { value: "90", label: "90s", seconds: 90 },
  { value: "custom", label: "Custom", seconds: null },
  { value: "auto", label: "Auto", seconds: null },
];

export const INTENSITIES: { value: AiSettings["intensity"]; label: string; hint: string }[] = [
  { value: "light", label: "Light", hint: "Keep more of the original footage" },
  { value: "balanced", label: "Balanced", hint: "Even mix of trimming and keeping" },
  { value: "aggressive", label: "Aggressive", hint: "Cut hard, keep only the best moments" },
];

export const MUSIC_MOODS: { value: AiSettings["musicMood"] & string; label: string }[] = [
  { value: "cinematic", label: "Cinematic" },
  { value: "energetic", label: "Energetic" },
  { value: "relaxing", label: "Relaxing" },
  { value: "happy", label: "Happy" },
  { value: "dramatic", label: "Dramatic" },
];

export const SUBTITLE_LANGUAGES: { value: AiSettings["subtitleLanguage"]; label: string }[] = [
  { value: "auto", label: "Auto-detect" },
  { value: "en", label: "English" },
  { value: "zh", label: "Chinese" },
  { value: "ms", label: "Malay" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
  { value: "de", label: "German" },
  { value: "it", label: "Italian" },
  { value: "pt", label: "Portuguese" },
  { value: "ru", label: "Russian" },
  { value: "ja", label: "Japanese" },
  { value: "ko", label: "Korean" },
  { value: "hi", label: "Hindi" },
  { value: "ar", label: "Arabic" },
  { value: "id", label: "Indonesian" },
  { value: "ta", label: "Tamil" },
  { value: "th", label: "Thai" },
  { value: "tr", label: "Turkish" },
  { value: "vi", label: "Vietnamese" },
];

/** One-click caption looks. Each is a complete CaptionStyle (editing any field switches to "custom"). */
export const CAPTION_PRESETS: { value: Exclude<CaptionStyle["preset"], "custom" | undefined>; label: string; style: CaptionStyle }[] = [
  { value: "classic", label: "Classic", style: { fontSize: "medium", position: "bottom", color: "#FFFFFF", background: "box",
    highlightColor: "#FFD700", outlineColor: "#000000", uppercase: false, preset: "classic", karaoke: false, animation: "none" } },
  { value: "bold", label: "Bold", style: { fontSize: "large", position: "bottom", color: "#FFFFFF", background: "outline",
    highlightColor: "#FFD700", outlineColor: "#000000", uppercase: true, preset: "bold", karaoke: false, animation: "pop" } },
  { value: "karaoke", label: "Karaoke", style: { fontSize: "large", position: "bottom", color: "#FFFFFF", background: "outline",
    highlightColor: "#FFD700", outlineColor: "#000000", uppercase: false, preset: "karaoke", karaoke: true, animation: "none" } },
  { value: "dynamic", label: "Dynamic", style: { fontSize: "large", position: "center", color: "#FFFFFF", background: "outline",
    highlightColor: "#00E5FF", outlineColor: "#000000", uppercase: true, preset: "dynamic", karaoke: true, animation: "pop" } },
  { value: "cinematic", label: "Cinematic", style: { fontSize: "small", position: "bottom", color: "#F5F5F5", background: "outline",
    highlightColor: "#FFD700", outlineColor: "#000000", uppercase: false, preset: "cinematic", karaoke: false, animation: "fade" } },
];

export const SUBTITLE_PRESETS: { value: AiSettings["subtitlePreset"]; label: string }[] = [
  { value: "standard", label: "Standard" },
  { value: "bold", label: "Bold" },
  { value: "minimal", label: "Minimal" },
  { value: "social", label: "Social Media" },
  { value: "cinematic", label: "Cinematic" },
];

export const LOOKS: { value: Look; label: string; css: string }[] = [
  { value: "none", label: "Original", css: "none" },
  { value: "warm", label: "Warm", css: "sepia(0.25) saturate(1.1)" },
  { value: "cool", label: "Cool", css: "hue-rotate(15deg) saturate(1.05) brightness(1.02)" },
  { value: "cinematic", label: "Cinematic", css: "contrast(1.12) saturate(0.9) brightness(0.95)" },
  { value: "vivid", label: "Vivid", css: "contrast(1.08) saturate(1.35)" },
  { value: "bw", label: "B&W", css: "grayscale(1) contrast(1.1)" },
  { value: "faded", label: "Faded", css: "contrast(0.9) saturate(0.8) brightness(1.04)" },
];

export const TRANSITIONS: { value: string; label: string; group: string }[] = [
  { value: "fade", label: "Crossfade", group: "Fade" },
  { value: "fadeblack", label: "Dip to black", group: "Fade" },
  { value: "fadewhite", label: "Flash (white)", group: "Fade" },
  { value: "fadegrays", label: "Dip to grey", group: "Fade" },
  { value: "fadefast", label: "Quick fade", group: "Fade" },
  { value: "fadeslow", label: "Slow fade", group: "Fade" },
  { value: "dissolve", label: "Dissolve", group: "Fade" },
  { value: "pixelize", label: "Pixelize", group: "Fade" },
  { value: "hblur", label: "Blur", group: "Fade" },
  { value: "wipeleft", label: "Wipe left", group: "Wipe" },
  { value: "wiperight", label: "Wipe right", group: "Wipe" },
  { value: "wipeup", label: "Wipe up", group: "Wipe" },
  { value: "wipedown", label: "Wipe down", group: "Wipe" },
  { value: "wipetl", label: "Wipe top-left", group: "Wipe" },
  { value: "wipebr", label: "Wipe bottom-right", group: "Wipe" },
  { value: "slideleft", label: "Slide left", group: "Slide" },
  { value: "slideright", label: "Slide right", group: "Slide" },
  { value: "slideup", label: "Slide up", group: "Slide" },
  { value: "slidedown", label: "Slide down", group: "Slide" },
  { value: "smoothleft", label: "Smooth left", group: "Slide" },
  { value: "smoothright", label: "Smooth right", group: "Slide" },
  { value: "coverleft", label: "Cover left", group: "Slide" },
  { value: "coverright", label: "Cover right", group: "Slide" },
  { value: "revealleft", label: "Reveal left", group: "Slide" },
  { value: "revealright", label: "Reveal right", group: "Slide" },
  { value: "circleopen", label: "Circle open", group: "Shape" },
  { value: "circleclose", label: "Circle close", group: "Shape" },
  { value: "circlecrop", label: "Circle crop", group: "Shape" },
  { value: "rectcrop", label: "Rectangle crop", group: "Shape" },
  { value: "radial", label: "Radial", group: "Shape" },
  { value: "zoomin", label: "Zoom in", group: "Shape" },
  { value: "squeezeh", label: "Squeeze horizontal", group: "Shape" },
  { value: "squeezev", label: "Squeeze vertical", group: "Shape" },
  { value: "vertopen", label: "Vertical open", group: "Shape" },
  { value: "horzopen", label: "Horizontal open", group: "Shape" },
  { value: "diagtl", label: "Diagonal", group: "Shape" },
  { value: "hlslice", label: "Slice left", group: "Slice" },
  { value: "hrslice", label: "Slice right", group: "Slice" },
  { value: "vuslice", label: "Slice up", group: "Slice" },
  { value: "vdslice", label: "Slice down", group: "Slice" },
  { value: "hlwind", label: "Wind left", group: "Slice" },
  { value: "hrwind", label: "Wind right", group: "Slice" },
  { value: "vuwind", label: "Wind up", group: "Slice" },
  { value: "vdwind", label: "Wind down", group: "Slice" },
];

/** Styles shown by default, in the order users meet them. The rest stay available under "More styles". */
export const PRIMARY_STYLES: Style[] = ["auto", "cinematic", "energetic", "minimal", "vlog", "documentary", "professional"];

/** An empty EDL that follows the project's current style settings (for manual timeline building). */
export function emptyEdl(doc: ProjectDoc): Edl {
  const s = STYLES[doc.style];
  const st = doc.settings;
  return {
    version: 1,
    style: doc.style,
    aspect: doc.aspect,
    fit: st.smartCrop ? "crop" : "blur",
    clips: [],
    transition: st.transitions ? { ...s.transition } : null,
    look: st.look ?? s.look,
    music: st.musicId ? { mediaId: st.musicId, volume: st.musicVolume, duck: true } : null,
    audioClips: st.musicId ? [{ id: "a0", mediaId: st.musicId, kind: "music", start: 0, trimIn: 0, duration: null, volume: st.musicVolume, fadeIn: 0, fadeOut: 0, loop: true, duck: true }] : [],
    markers: [],
    captions: [],
    captionStyle: { fontSize: "medium", position: "bottom", color: "#FFFFFF", background: "box", highlightColor: "#FFD700", uppercase: false },
    burnCaptions: st.burnCaptions,
    titles: [],
    audio: { normalize: st.normalizeAudio, lufs: s.lufs, clean: s.clean, fades: s.fades },
    beat: null,
    notes: ["Timeline built manually."],
    videoType: null,
    resolvedStyle: null,
  };
}

// Export bitrate table (kbps), mirrors backend/services/rendering.py QUALITY.
export const QUALITY = {
  draft: { 720: 2500, 1080: 4500, 2160: 18000, audio: 128, label: "Draft" },
  standard: { 720: 5000, 1080: 8000, 2160: 35000, audio: 160, label: "Standard" },
  high: { 720: 8000, 1080: 12000, 2160: 50000, audio: 192, label: "High" },
} as const;

export function estimateBytes(duration: number, quality: keyof typeof QUALITY, res: 720 | 1080 | 2160, fps: number) {
  const q = QUALITY[quality];
  const video = fps > 30 ? q[res] * 1.5 : q[res];
  return ((video + q.audio) * 1000 * duration * 1.01) / 8;
}

export const DEFAULT_CAPTION_STYLE: CaptionStyle = CAPTION_PRESETS[0].style;

/** New caption text keeps karaoke working: the old span is shared out over the new words by length. */
export function retimeWords(text: string, start: number, end: number): { word: string; start: number; end: number }[] {
  const tokens = text.split(/\s+/).filter(Boolean);
  const total = tokens.reduce((a, t) => a + t.length + 1, 0) || 1;
  let at = start;
  return tokens.map((word) => {
    const len = ((word.length + 1) / total) * (end - start);
    const w = { word, start: Math.round(at * 1000) / 1000, end: Math.round((at + len) * 1000) / 1000 };
    at += len;
    return w;
  });
}

/** Resolved text-overlay settings (older titles only had text, start, duration and a position preset). */
export const TITLE_DEFAULTS = {
  x: 0.5, size: 0.07, rotation: 0, font: "Arial" as const, weight: "bold" as const, color: "#FFFFFF", opacity: 1,
  align: "center" as const, strokeColor: "#000000", strokeWidth: 0, shadow: false, background: "#000000",
  backgroundOpacity: 0.65, animation: "none" as import("../types").TextAnimation,
};
export const TITLE_Y_PRESET = { top: 0.12, center: 0.5, bottom: 0.88 } as const;
export function titleLook(t: import("../types").Title) {
  return { ...TITLE_DEFAULTS, ...Object.fromEntries(Object.entries(t).filter(([, v]) => v !== undefined && v !== null)) } as typeof TITLE_DEFAULTS &
    import("../types").Title & { y: number };
}
