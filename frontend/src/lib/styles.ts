// Style metadata. Rendering parameters mirror backend/services/editing.py STYLES.
import type { AiSettings, Aspect, Edl, Look, ProjectDoc, Style } from "../types";

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
    defaults: { removeSilence: false, beatSync: true, captions: false },
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
    defaults: { removeSilence: false, captions: false },
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
    defaults: { removeSilence: true, captions: true },
  },
};

export const ASPECTS: { value: Aspect; label: string; hint: string }[] = [
  { value: "16:9", label: "16:9", hint: "Landscape" },
  { value: "9:16", label: "9:16", hint: "Portrait" },
  { value: "1:1", label: "1:1", hint: "Square" },
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

export const TRANSITIONS: { value: string; label: string }[] = [
  { value: "fade", label: "Crossfade" },
  { value: "fadeblack", label: "Dip to black" },
  { value: "fadewhite", label: "Flash (white)" },
  { value: "dissolve", label: "Dissolve" },
  { value: "wipeleft", label: "Wipe left" },
  { value: "wiperight", label: "Wipe right" },
  { value: "slideleft", label: "Slide left" },
  { value: "slideright", label: "Slide right" },
  { value: "circleopen", label: "Circle open" },
  { value: "pixelize", label: "Pixelize" },
];

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
    captions: [],
    burnCaptions: st.burnCaptions,
    titles: [],
    audio: { normalize: st.normalizeAudio, lufs: s.lufs, clean: s.clean, fades: s.fades },
    beat: null,
    notes: ["Timeline built manually."],
  };
}

// Export bitrate table (kbps), mirrors backend/services/rendering.py QUALITY.
export const QUALITY = {
  draft: { 720: 2500, 1080: 4500, audio: 128, label: "Draft" },
  standard: { 720: 5000, 1080: 8000, audio: 160, label: "Standard" },
  high: { 720: 8000, 1080: 12000, audio: 192, label: "High" },
} as const;

export function estimateBytes(duration: number, quality: keyof typeof QUALITY, res: 720 | 1080, fps: number) {
  const q = QUALITY[quality];
  const video = fps > 30 ? q[res] * 1.5 : q[res];
  return ((video + q.audio) * 1000 * duration * 1.01) / 8;
}
