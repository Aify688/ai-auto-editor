// Output-timeline layout of an EDL. Mirrors backend/services/editing/layout.py and the
// grouping/xfade offsets in video_editor/engine.py, so what the timeline shows is what renders.
import type { Caption, Edl, EdlClip } from "../types";

export interface LaidClip {
  clip: EdlClip;
  index: number;
  group: number;
  outStart: number;
  outEnd: number;
}

export interface CaptionSpan {
  caption: Caption;
  outStart: number;
  outEnd: number;
  /** Words (with output-timeline timing) that are still inside this clip; empty without word timestamps. */
  words: { word: string; outStart: number; outEnd: number }[];
  /** The video clip this span sits in (output times) and the source time its start corresponds to. */
  clipOutStart: number;
  clipOutEnd: number;
  srcLo: number;
}

export interface Layout {
  clips: LaidClip[];
  duration: number;
  transition: number; // effective transition length in seconds (0 = hard cuts)
}

const round = (v: number, n = 3) => Math.round(v * 10 ** n) / 10 ** n;

/** Output length of a clip: a freeze frame lasts its hold time, otherwise the source range divided by its speed. */
export function clipDuration(c: Pick<EdlClip, "srcStart" | "srcEnd" | "speed" | "freeze">): number {
  return c.freeze ? c.freeze : (c.srcEnd - c.srcStart) / (c.speed || 1);
}

/** Source seconds consumed per output second (1 = normal speed). */
export function clipRate(c: Pick<EdlClip, "srcStart" | "srcEnd" | "speed" | "freeze">): number {
  return (c.srcEnd - c.srcStart) / clipDuration(c);
}

export function groupIndexes(clips: EdlClip[]): number[] {
  const out: number[] = [];
  let g = -1;
  clips.forEach((c, i) => {
    if (i === 0 || c.mediaId !== clips[i - 1].mediaId || c.sceneBreak) g += 1;
    out.push(g);
  });
  return out;
}

export function effectiveTransition(edl: Pick<Edl, "clips" | "transition">): number {
  if (!edl.transition || edl.clips.length < 2) return 0;
  const groups = groupIndexes(edl.clips);
  const n = groups.length ? groups[groups.length - 1] + 1 : 0;
  if (n < 2) return 0;
  const durs = new Array(n).fill(0);
  edl.clips.forEach((c, i) => (durs[groups[i]] += clipDuration(c)));
  const fit = round(Math.min(edl.transition.duration, Math.min(...durs) / 2 - 0.05), 2);
  return fit < 0.15 ? 0 : fit;
}

export function layout(edl: Pick<Edl, "clips" | "transition">): Layout {
  const d = effectiveTransition(edl);
  const groups = groupIndexes(edl.clips);
  const clips: LaidClip[] = [];
  let acc = 0;
  let groupStart = 0;
  let t = 0;
  edl.clips.forEach((clip, i) => {
    const g = groups[i];
    if (i > 0 && g !== groups[i - 1]) {
      groupStart = acc - d;
      t = groupStart;
    }
    const dur = clipDuration(clip);
    clips.push({ clip, index: i, group: g, outStart: round(t), outEnd: round(t + dur) });
    t += dur;
    acc = t;
  });
  return { clips, duration: round(acc), transition: d };
}

/** Map source-time captions onto the output timeline (a cue can span several clips). */
export function captionSpans(captions: Caption[], laid: LaidClip[]): CaptionSpan[] {
  const out: CaptionSpan[] = [];
  for (const caption of captions) {
    for (const lc of laid) {
      if (lc.clip.mediaId !== caption.mediaId) continue;
      const lo = Math.max(lc.clip.srcStart, caption.srcStart);
      const hi = Math.min(lc.clip.srcEnd, caption.srcEnd);
      if (hi - lo > 0.05) {
        const rate = clipRate(lc.clip);
        const at = (x: number) => round(lc.outStart + (Math.min(hi, Math.max(lo, x)) - lc.clip.srcStart) / rate);
        out.push({
          caption,
          outStart: round(lc.outStart + (lo - lc.clip.srcStart) / rate),
          outEnd: round(lc.outStart + (hi - lc.clip.srcStart) / rate),
          clipOutStart: lc.outStart,
          clipOutEnd: lc.outEnd,
          srcLo: lo,
          words: (caption.words ?? [])
            .filter((w) => w.end > lo + 0.02 && w.start < hi - 0.02)
            .map((w) => ({ word: w.word, outStart: at(w.start), outEnd: at(w.end) })),
        });
      }
    }
  }
  return out.sort((a, b) => a.outStart - b.outStart);
}

/** Which clip is visible at output time `t` (later clip wins inside a transition overlap). */
export function clipAt(laid: LaidClip[], t: number): LaidClip | null {
  let hit: LaidClip | null = null;
  for (const lc of laid) if (t >= lc.outStart && t < lc.outEnd) hit = lc;
  if (!hit && laid.length && t >= laid[laid.length - 1].outEnd - 1e-3) hit = laid[laid.length - 1];
  return hit;
}

/** Crop offset (0..1, CSS object-position semantics) that centres a subject; mirrors editing.crop_offset. */
export function cropOffset(fx: number, fy: number, srcW: number, srcH: number, aspect: string): [number, number] {
  if (aspect === "original") return [0.5, 0.5]; // output follows the source's own aspect ratio
  const [a, b] = aspect.split(":").map(Number);
  const outAr = a / b;
  const srcAr = srcW / Math.max(1, srcH);
  let ox = 0.5;
  let oy = 0.5;
  if (srcAr > outAr + 1e-3) {
    const r = outAr / srcAr;
    ox = Math.min(1, Math.max(0, (fx - r / 2) / (1 - r)));
  } else if (srcAr < outAr - 1e-3) {
    const r = srcAr / outAr;
    oy = Math.min(1, Math.max(0, (fy - r / 2) / (1 - r)));
  }
  return [ox, oy];
}
