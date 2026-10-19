// Pure editing rules for the audio, text and caption lanes. The UI only turns pointer movement into seconds and
// calls these; the same numbers are what gets saved in the EDL and rendered, so preview and export agree.
import type { AudioClip, Caption, Edl, Title } from "../types";
import { uid } from "./format";
import type { CaptionSpan, Layout } from "./layout";

export const MIN_LEN = 0.2;
export const SNAP_PX = 8;
const r3 = (v: number) => Math.round(v * 1000) / 1000;
const clampN = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/* ------------------------------------------------------------------ snapping */
export interface Snap { value: number; snapped: number | null }

/** Snap a time to the nearest target within SNAP_PX screen pixels. */
export function snapValue(value: number, points: number[], pps: number): Snap {
  let best: number | null = null;
  let bd = SNAP_PX / pps;
  for (const p of points) {
    const d = Math.abs(p - value);
    if (d <= bd) {
      bd = d;
      best = p;
    }
  }
  return best === null ? { value, snapped: null } : { value: best, snapped: best };
}

/** Snap whichever edge of [start, start+len] is closest to a target. Returns the new start. */
export function snapRange(start: number, len: number, points: number[], pps: number): { start: number; snapped: number | null } {
  const a = snapValue(start, points, pps);
  const b = snapValue(start + len, points, pps);
  const da = a.snapped === null ? Infinity : Math.abs(a.value - start);
  const db = b.snapped === null ? Infinity : Math.abs(b.value - (start + len));
  if (da === Infinity && db === Infinity) return { start, snapped: null };
  return da <= db ? { start: a.value, snapped: a.snapped } : { start: b.value - len, snapped: b.snapped };
}

export type ItemRef = { kind: "audio" | "text" | "caption" | "marker"; id: string };

/** Everything an edge can snap to: video cuts, other clips' edges, markers, the playhead and the timeline ends. */
export function snapPoints(edl: Edl, lay: Layout, playhead: number, mediaDur: (id: string) => number | undefined, exclude?: ItemRef): number[] {
  const pts = [0, lay.duration, playhead, ...(edl.markers ?? [])];
  for (const lc of lay.clips) pts.push(lc.outStart, lc.outEnd);
  for (const a of edl.audioClips ?? []) {
    if (exclude?.kind === "audio" && exclude.id === a.id) continue;
    pts.push(a.start, a.start + audioLength(a, mediaDur(a.mediaId), lay.duration));
  }
  for (const t of edl.titles) {
    if (exclude?.kind === "text" && exclude.id === t.id) continue;
    pts.push(t.start, t.start + t.duration);
  }
  return [...new Set(pts.map(r3))].sort((x, y) => x - y);
}

/* ------------------------------------------------------------------ audio clips */
/** Visible length on the timeline: the renderer's rule (cut at the video end; without looping, at the source end). */
export function audioLength(c: AudioClip, srcDur: number | undefined, total: number): number {
  const room = Math.max(0, total - c.start);
  let len = c.duration ?? (c.loop || !srcDur ? room : srcDur - c.trimIn);
  if (!c.loop && srcDur) len = Math.min(len, srcDur - c.trimIn);
  return Math.max(0, Math.min(len, room));
}

export interface LaneCtx {
  total: number;
  points: number[];
  pps: number;
  /** Other clips in the SAME lane (edges in timeline seconds). Used where overlaps are not allowed. */
  others: { start: number; end: number }[];
}
export interface AudioCtx extends LaneCtx { srcDur?: number }

/** Free space around a range: the nearest neighbour end on its left and start on its right. */
function gap(start: number, end: number, others: { start: number; end: number }[], total: number): { lo: number; hi: number } {
  let lo = 0;
  let hi = total;
  for (const o of others) {
    if (o.end <= start + 1e-6) lo = Math.max(lo, o.end);
    else if (o.start >= end - 1e-6) hi = Math.min(hi, o.start);
  }
  return { lo, hi };
}

export function moveAudio(c: AudioClip, delta: number, ctx: AudioCtx): { clip: AudioClip; snapped: number | null } {
  const len = audioLength(c, ctx.srcDur, ctx.total);
  const g = gap(c.start, c.start + len, ctx.others, ctx.total);
  const lo = g.lo;
  const hi = Math.max(lo, g.hi - len);
  let start = clampN(c.start + delta, lo, hi);
  const s = snapRange(start, len, ctx.points, ctx.pps);
  start = clampN(s.start, lo, hi);
  return { clip: { ...c, start: r3(start), duration: r3(len) }, snapped: s.snapped !== null && Math.abs(start - s.start) < 1e-6 ? s.snapped : null };
}

/** Drag the left edge: the in-point moves with it, so the sound stays where it was and only the start changes. */
export function trimAudioStart(c: AudioClip, delta: number, ctx: AudioCtx): { clip: AudioClip; snapped: number | null } {
  const len = audioLength(c, ctx.srcDur, ctx.total);
  const end = c.start + len;
  const g = gap(c.start, end, ctx.others, ctx.total);
  const lo = Math.max(g.lo, c.start - c.trimIn);                     // cannot reach before the start of the file
  const hi = end - MIN_LEN;
  let start = clampN(c.start + delta, lo, hi);
  const s = snapValue(start, ctx.points, ctx.pps);
  start = clampN(s.value, lo, hi);
  return {
    clip: { ...c, start: r3(start), trimIn: r3(c.trimIn + (start - c.start)), duration: r3(end - start) },
    snapped: s.snapped !== null && Math.abs(start - s.value) < 1e-6 ? s.snapped : null,
  };
}

/** Drag the right edge: longer reveals more of the source (or loops it), shorter hides the tail. */
export function trimAudioEnd(c: AudioClip, delta: number, ctx: AudioCtx): { clip: AudioClip; snapped: number | null } {
  const len = audioLength(c, ctx.srcDur, ctx.total);
  const end = c.start + len;
  const g = gap(c.start, end, ctx.others, ctx.total);
  let hi = g.hi;
  if (!c.loop && ctx.srcDur) hi = Math.min(hi, c.start + (ctx.srcDur - c.trimIn));
  const lo = c.start + MIN_LEN;
  let newEnd = clampN(end + delta, lo, Math.max(lo, hi));
  const s = snapValue(newEnd, ctx.points, ctx.pps);
  newEnd = clampN(s.value, lo, Math.max(lo, hi));
  return { clip: { ...c, duration: r3(newEnd - c.start) }, snapped: s.snapped !== null && Math.abs(newEnd - s.value) < 1e-6 ? s.snapped : null };
}

export function splitAudio(c: AudioClip, t: number, ctx: { srcDur?: number; total: number }): [AudioClip, AudioClip] | null {
  const len = audioLength(c, ctx.srcDur, ctx.total);
  if (t < c.start + MIN_LEN || t > c.start + len - MIN_LEN) return null;
  const into = t - c.start;
  let trim2 = c.trimIn + into;
  if (c.loop && ctx.srcDur) trim2 = c.trimIn + (into % Math.max(MIN_LEN, ctx.srcDur - c.trimIn));
  const a: AudioClip = { ...c, duration: r3(into), fadeOut: 0 };
  const b: AudioClip = { ...c, id: uid("a"), start: r3(t), trimIn: r3(trim2), duration: r3(len - into), fadeIn: 0 };
  return [a, b];
}

/** A copy placed right after the original, or in the next free gap; null when the timeline has no room for it. */
export function duplicateAudio(c: AudioClip, ctx: { srcDur?: number; total: number; others: { start: number; end: number }[] }): AudioClip | null {
  const len = audioLength(c, ctx.srcDur, ctx.total) || MIN_LEN;
  const busy = [...ctx.others, { start: c.start, end: c.start + len }].sort((x, y) => x.start - y.start);
  let at = c.start + len;
  for (const o of busy) if (o.start < at + len - 1e-6 && o.end > at + 1e-6) at = o.end;
  if (at + len > ctx.total + 1e-6) return null;
  return { ...c, id: uid("a"), start: r3(at), duration: r3(len) };
}

/** Audio clips of one kind of lane must not overlap: a clip's neighbours, excluding itself. */
export const laneOthers = (clips: AudioClip[], id: string, dur: (mediaId: string) => number | undefined, total: number) =>
  clips.filter((x) => x.id !== id).map((x) => ({ start: x.start, end: x.start + audioLength(x, dur(x.mediaId), total) }));

/* ------------------------------------------------------------------ text overlays (may overlap: they stack in rows) */
export interface TextCtx { total: number; points: number[]; pps: number }

export function moveTitle(t: Title, delta: number, ctx: TextCtx): { title: Title; snapped: number | null } {
  const hi = Math.max(0, ctx.total - t.duration);
  let start = clampN(t.start + delta, 0, hi);
  const s = snapRange(start, t.duration, ctx.points, ctx.pps);
  start = clampN(s.start, 0, hi);
  return { title: { ...t, start: r3(start) }, snapped: s.snapped !== null && Math.abs(start - s.start) < 1e-6 ? s.snapped : null };
}

export function trimTitleStart(t: Title, delta: number, ctx: TextCtx): { title: Title; snapped: number | null } {
  const end = t.start + t.duration;
  const lo = Math.max(0, end - 60);
  let start = clampN(t.start + delta, lo, end - MIN_LEN);
  const s = snapValue(start, ctx.points, ctx.pps);
  start = clampN(s.value, lo, end - MIN_LEN);
  return { title: { ...t, start: r3(start), duration: r3(end - start) }, snapped: s.snapped !== null && Math.abs(start - s.value) < 1e-6 ? s.snapped : null };
}

export function trimTitleEnd(t: Title, delta: number, ctx: TextCtx): { title: Title; snapped: number | null } {
  const hi = Math.min(ctx.total, t.start + 60);
  let end = clampN(t.start + t.duration + delta, t.start + MIN_LEN, Math.max(t.start + MIN_LEN, hi));
  const s = snapValue(end, ctx.points, ctx.pps);
  end = clampN(s.value, t.start + MIN_LEN, Math.max(t.start + MIN_LEN, hi));
  return { title: { ...t, duration: r3(end - t.start) }, snapped: s.snapped !== null && Math.abs(end - s.value) < 1e-6 ? s.snapped : null };
}

export function splitTitle(t: Title, at: number): [Title, Title] | null {
  if (at < t.start + MIN_LEN || at > t.start + t.duration - MIN_LEN) return null;
  return [{ ...t, duration: r3(at - t.start) }, { ...t, id: uid("t"), start: r3(at), duration: r3(t.start + t.duration - at) }];
}

export function duplicateTitle(t: Title, total: number): Title {
  const start = t.start + t.duration + MIN_LEN <= total ? t.start + t.duration : Math.max(0, Math.min(t.start + 0.3, total - t.duration));
  return { ...t, id: uid("t"), start: r3(start), x: Math.min(1, (t.x ?? 0.5) + 0.03), y: Math.min(1, (t.y ?? 0.5) + 0.03) };
}

/** Rows for overlapping text clips (first-fit), so nothing is ever hidden behind another clip. */
export function assignLanes(items: { id: string; start: number; end: number }[]): Map<string, number> {
  const out = new Map<string, number>();
  const ends: number[] = [];
  for (const it of [...items].sort((a, b) => a.start - b.start || a.end - b.end)) {
    let lane = ends.findIndex((e) => e <= it.start + 1e-6);
    if (lane < 0) {
      lane = ends.length;
      ends.push(it.end);
    } else ends[lane] = it.end;
    out.set(it.id, lane);
  }
  return out;
}

/* ------------------------------------------------------------------ captions (stored in SOURCE time; edited in timeline time) */
function remember(c: Caption): Caption {
  return c.manual ? c : { ...c, manual: true, origStart: c.srcStart, origEnd: c.srcEnd, wordShift: 0 };
}

/** Move/resize a caption by the given source-time deltas. The transcript (text and words) is kept. */
export function retimeCaption(c: Caption, dStart: number, dEnd: number): Caption {
  const base = remember(c);
  const moved = Math.abs(dStart - dEnd) < 1e-6;            // a pure move carries the words with it, a resize does not
  return {
    ...base,
    srcStart: r3(Math.max(0, c.srcStart + dStart)),
    srcEnd: r3(Math.max(c.srcStart + dStart + MIN_LEN, c.srcEnd + dEnd)),
    words: moved && c.words ? c.words.map((w) => ({ ...w, start: r3(w.start + dStart), end: r3(w.end + dStart) })) : c.words,
    wordShift: r3((base.wordShift ?? 0) + (moved ? dStart : 0)),
  };
}

/** Back to the times Whisper produced. */
export function resetCaption(c: Caption): Caption {
  if (!c.manual || c.origStart == null || c.origEnd == null) return c;
  const back = -(c.wordShift ?? 0);
  return {
    ...c, srcStart: c.origStart, srcEnd: c.origEnd, manual: false, origStart: null, origEnd: null, wordShift: 0,
    words: c.words ? c.words.map((w) => ({ ...w, start: r3(w.start + back), end: r3(w.end + back) })) : c.words,
  };
}

export interface CaptionCtx { points: number[]; pps: number; others: { start: number; end: number }[] }

function capBounds(s: CaptionSpan, others: CaptionCtx["others"]) {
  const g = gap(s.outStart, s.outEnd, others, s.clipOutEnd);
  return { lo: Math.max(s.clipOutStart, g.lo), hi: Math.min(s.clipOutEnd, g.hi) };
}

export function moveCaption(s: CaptionSpan, delta: number, ctx: CaptionCtx): { caption: Caption; snapped: number | null; start: number } {
  const len = s.outEnd - s.outStart;
  const b = capBounds(s, ctx.others);
  const hi = Math.max(b.lo, b.hi - len);
  let start = clampN(s.outStart + delta, b.lo, hi);
  const sn = snapRange(start, len, ctx.points, ctx.pps);
  start = clampN(sn.start, b.lo, hi);
  const d = start - s.outStart;
  return { caption: Math.abs(d) < 1e-6 ? s.caption : retimeCaption(s.caption, d, d), snapped: sn.snapped !== null && Math.abs(start - sn.start) < 1e-6 ? sn.snapped : null, start };
}

export function trimCaptionStart(s: CaptionSpan, delta: number, ctx: CaptionCtx): { caption: Caption; snapped: number | null; start: number } {
  const b = capBounds(s, ctx.others);
  let start = clampN(s.outStart + delta, b.lo, s.outEnd - MIN_LEN);
  const sn = snapValue(start, ctx.points, ctx.pps);
  start = clampN(sn.value, b.lo, s.outEnd - MIN_LEN);
  const d = start - s.outStart;
  return { caption: Math.abs(d) < 1e-6 ? s.caption : retimeCaption(s.caption, d, 0), snapped: sn.snapped !== null && Math.abs(start - sn.value) < 1e-6 ? sn.snapped : null, start };
}

export function trimCaptionEnd(s: CaptionSpan, delta: number, ctx: CaptionCtx): { caption: Caption; snapped: number | null; end: number } {
  const b = capBounds(s, ctx.others);
  let end = clampN(s.outEnd + delta, s.outStart + MIN_LEN, Math.max(s.outStart + MIN_LEN, b.hi));
  const sn = snapValue(end, ctx.points, ctx.pps);
  end = clampN(sn.value, s.outStart + MIN_LEN, Math.max(s.outStart + MIN_LEN, b.hi));
  const d = end - s.outEnd;
  return { caption: Math.abs(d) < 1e-6 ? s.caption : retimeCaption(s.caption, 0, d), snapped: sn.snapped !== null && Math.abs(end - sn.value) < 1e-6 ? sn.snapped : null, end };
}

/** Split a caption at timeline time t. Words keep their own timing; without words the text splits at a word boundary. */
export function splitCaption(s: CaptionSpan, t: number): [Caption, Caption] | null {
  if (t < s.outStart + MIN_LEN || t > s.outEnd - MIN_LEN) return null;
  const src = r3(s.srcLo + (t - s.outStart));
  const c = remember(s.caption);
  const words = c.words ?? [];
  let a = words.filter((w) => (w.start + w.end) / 2 < src);
  let b = words.filter((w) => (w.start + w.end) / 2 >= src);
  let textA: string, textB: string;
  if (words.length && a.length && b.length) {
    textA = a.map((w) => w.word).join(" ");
    textB = b.map((w) => w.word).join(" ");
  } else {
    const toks = c.text.split(/\s+/).filter(Boolean);
    const k = clampN(Math.round((toks.length * (src - c.srcStart)) / Math.max(MIN_LEN, c.srcEnd - c.srcStart)), 1, Math.max(1, toks.length - 1));
    textA = toks.slice(0, k).join(" ");
    textB = toks.slice(k).join(" ");
    a = [];
    b = [];
    if (!textB) return null;
  }
  return [
    { ...c, text: textA, srcEnd: src, words: a.length ? a : null },
    { ...c, id: uid("t"), text: textB, srcStart: src, words: b.length ? b : null },
  ];
}

/** A copy right after the original inside the same clip, or null when the clip has no room. */
export function duplicateCaption(s: CaptionSpan, others: { start: number; end: number }[]): Caption | null {
  const len = s.outEnd - s.outStart;
  const at = s.outEnd;
  if (at + len > s.clipOutEnd + 1e-6) return null;
  if (others.some((o) => o.start < at + len - 1e-6 && o.end > at + 1e-6)) return null;
  const c = remember(s.caption);
  return { ...c, id: uid("t"), srcStart: r3(c.srcStart + len), srcEnd: r3(c.srcEnd + len),
    words: c.words ? c.words.map((w) => ({ ...w, start: r3(w.start + len), end: r3(w.end + len) })) : c.words };
}

/* ------------------------------------------------------------------ markers */
export function toggleMarker(markers: number[], t: number): number[] {
  const near = markers.findIndex((m) => Math.abs(m - t) < 0.06);
  const next = near >= 0 ? markers.filter((_, i) => i !== near) : [...markers, r3(t)];
  return next.sort((a, b) => a - b);
}

/* ------------------------------------------------------------------ music helpers shared with the AI panel */
/** The first music clip (the one the AI panel and recommendations talk about). */
export const primaryMusic = (edl: Edl): AudioClip | undefined => edl.audioClips?.find((c) => c.kind === "music");

/** Replace/add/remove the primary music clip, keeping the legacy `music` mirror in step. */
export function setPrimaryMusic(edl: Edl, patch: Partial<AudioClip> & { mediaId?: string } | null): Edl {
  const clips = [...(edl.audioClips ?? [])];
  const i = clips.findIndex((c) => c.kind === "music");
  if (patch === null) {
    if (i >= 0) clips.splice(i, 1);
  } else if (i >= 0) {
    clips[i] = { ...clips[i], ...patch };
  } else if (patch.mediaId) {
    clips.unshift({ id: uid("a"), mediaId: patch.mediaId, kind: "music", start: 0, trimIn: 0, duration: null, volume: 0.35,
      fadeIn: 0, fadeOut: 0, loop: true, duck: true, ...patch });
  }
  const first = clips.find((c) => c.kind === "music");
  return { ...edl, audioClips: clips, music: first ? { mediaId: first.mediaId, volume: first.volume, duck: first.duck } : null };
}

/** Replace the audio timeline, keeping the legacy `music` mirror (the first music clip) in step. */
export function withAudioClips(edl: Edl, clips: AudioClip[]): Edl {
  const first = clips.find((c) => c.kind === "music");
  return { ...edl, audioClips: clips, music: first ? { mediaId: first.mediaId, volume: first.volume, duck: first.duck } : null };
}
