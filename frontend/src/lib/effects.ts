// Library of per-clip effects and colour filters. Ids mirror video_editor/effects.py; `css` approximates the
// FFmpeg result for the live preview and the library thumbnails (some effects have no CSS equivalent).
import type { ClipEffect, ClipFilter } from "../types";

export interface EffectDef {
  id: string;
  label: string;
  /** CSS filter for an amount in 0..1; null when the preview cannot show it. */
  css: ((a: number) => string) | null;
  /** The amount slider is meaningless (on/off effect). */
  fixed?: boolean;
}

export const EFFECTS: EffectDef[] = [
  { id: "blur", label: "Blur", css: (a) => `blur(${1 + a * 7}px)` },
  { id: "sharpen", label: "Sharpen", css: (a) => `contrast(${1 + a * 0.25})` },
  { id: "vignette", label: "Vignette", css: null },
  { id: "grain", label: "Film grain", css: null },
  { id: "glitch", label: "RGB glitch", css: (a) => `hue-rotate(${a * 25}deg) saturate(${1 + a * 0.6})` },
  { id: "pixelate", label: "Pixelate", css: null },
  { id: "mono", label: "Black & white", css: (a) => `grayscale(${a})` },
  { id: "sepia", label: "Sepia", css: (a) => `sepia(${a})` },
  { id: "invert", label: "Invert", css: (a) => `invert(${a})` },
  { id: "flip_h", label: "Flip horizontal", css: null, fixed: true },
  { id: "flip_v", label: "Flip vertical", css: null, fixed: true },
  { id: "shake", label: "Shake", css: null },
  { id: "dream", label: "Dream glow", css: (a) => `blur(${a * 2}px) brightness(${1 + a * 0.12}) saturate(1.15)` },
];

export interface FilterDef {
  id: string;
  label: string;
  css: string;
}

export const FILTERS: FilterDef[] = [
  { id: "warm", label: "Warm", css: "sepia(0.25) saturate(1.1)" },
  { id: "cool", label: "Cool", css: "hue-rotate(15deg) saturate(1.05) brightness(1.02)" },
  { id: "cinematic", label: "Cinematic", css: "contrast(1.12) saturate(0.9) brightness(0.95)" },
  { id: "vivid", label: "Vivid", css: "contrast(1.08) saturate(1.35)" },
  { id: "bw", label: "B&W", css: "grayscale(1) contrast(1.1)" },
  { id: "faded", label: "Faded", css: "contrast(0.9) saturate(0.8) brightness(1.04)" },
  { id: "noir", label: "Noir", css: "grayscale(1) contrast(1.45) brightness(0.95)" },
  { id: "sunset", label: "Sunset", css: "sepia(0.35) saturate(1.4) hue-rotate(-12deg)" },
  { id: "teal_orange", label: "Teal & orange", css: "contrast(1.1) saturate(1.2) hue-rotate(-8deg) sepia(0.15)" },
  { id: "retro", label: "Retro", css: "sepia(0.7) contrast(0.95) brightness(1.02)" },
  { id: "fresh", label: "Fresh", css: "brightness(1.05) saturate(1.25) hue-rotate(6deg)" },
  { id: "matte", label: "Matte", css: "contrast(0.88) saturate(0.9) brightness(1.06)" },
];

const byId = <T extends { id: string }>(list: T[]) => new Map(list.map((x) => [x.id, x]));
const EFFECT_BY_ID = byId(EFFECTS);
const FILTER_BY_ID = byId(FILTERS);

/** Blend a CSS filter toward "none" by `s` (approximate: scales the numeric argument of each function). */
export function scaleCss(css: string, s: number): string {
  if (s >= 0.999) return css;
  return css.replace(/(\w[\w-]*)\(([-\d.]+)(deg|px)?\)/g, (_m, fn: string, n: string, unit = "") => {
    const v = Number(n);
    const neutral = fn === "contrast" || fn === "saturate" || fn === "brightness" ? 1 : 0;
    return `${fn}(${neutral + (v - neutral) * s}${unit})`;
  });
}

/** CSS filter string for one clip's filter + effects (empty when none are previewable). */
export function clipFilterCss(filter?: ClipFilter | null, effects?: ClipEffect[]): string {
  const parts: string[] = [];
  const f = filter && FILTER_BY_ID.get(filter.id);
  if (f) parts.push(scaleCss(f.css, filter!.strength));
  for (const e of effects ?? []) {
    const d = EFFECT_BY_ID.get(e.id);
    if (d?.css) parts.push(d.css(e.amount));
  }
  return parts.join(" ");
}

/** Flips are previewed with a transform. */
export function clipFlip(effects?: ClipEffect[]): string {
  const h = effects?.some((e) => e.id === "flip_h");
  const v = effects?.some((e) => e.id === "flip_v");
  return h || v ? `scale(${h ? -1 : 1}, ${v ? -1 : 1})` : "";
}

export function hasVignette(effects?: ClipEffect[]): number {
  return effects?.find((e) => e.id === "vignette")?.amount ?? 0;
}

export const MAX_EFFECTS = 6;
