// Pure EDL edit operations used by the timeline. Each returns a new EDL (or the same one if nothing changed).
import type { Edl, RemovedSegment } from "../types";
import { uid } from "./format";
import { clipRate, type Layout } from "./layout";

export const MIN_CLIP = 0.3;
const r3 = (v: number) => Math.round(v * 1000) / 1000;

/** Split the clip under output time `t` (or `clipId` if given). Both halves must be >= MIN_CLIP. */
export function splitAt(edl: Edl, lay: Layout, t: number, clipId?: string | null): { edl: Edl; newId: string } | null {
  const target = clipId
    ? lay.clips.find((c) => c.clip.id === clipId && t > c.outStart && t < c.outEnd)
    : [...lay.clips].reverse().find((c) => t > c.outStart && t < c.outEnd);
  if (!target) return null;
  if (target.clip.freeze) return null; // a freeze frame is one frame held; nothing to cut
  const at = r3(target.clip.srcStart + (t - target.outStart) * clipRate(target.clip));
  if (at - target.clip.srcStart < MIN_CLIP || target.clip.srcEnd - at < MIN_CLIP) return null;
  const first = { ...target.clip, srcEnd: at };
  const second = { ...target.clip, id: uid("c"), srcStart: at, sceneBreak: false }; // continuous: hard cut
  const clips = [...edl.clips];
  clips.splice(target.index, 1, first, second);
  return { edl: { ...edl, clips }, newId: second.id };
}

export function deleteClip(edl: Edl, clipId: string): Edl {
  const clips = edl.clips.filter((c) => c.id !== clipId);
  return clips.length === edl.clips.length ? edl : { ...edl, clips };
}

export function moveClip(edl: Edl, from: number, to: number): Edl {
  if (from === to || from < 0 || from >= edl.clips.length) return edl;
  const clips = [...edl.clips];
  const [c] = clips.splice(from, 1);
  const dest = to > from ? to - 1 : to;
  // a moved clip starts a new scene, so it gets the transition (if any) instead of a jump cut
  clips.splice(Math.max(0, Math.min(clips.length, dest)), 0, { ...c, sceneBreak: true });
  return { ...edl, clips };
}

export function trimClip(edl: Edl, clipId: string, edge: "start" | "end", value: number, mediaDuration: number): Edl {
  return {
    ...edl,
    clips: edl.clips.map((c) => {
      if (c.id !== clipId) return c;
      if (edge === "start") return { ...c, srcStart: r3(Math.max(0, Math.min(value, c.srcEnd - MIN_CLIP))) };
      return { ...c, srcEnd: r3(Math.min(mediaDuration, Math.max(value, c.srcStart + MIN_CLIP))) };
    }),
  };
}

/** Visible extent of each clip on the timeline: transition overlaps are split at their midpoint. */
export function displayBounds(lay: Layout): { start: number; end: number; transitionBefore: boolean }[] {
  return lay.clips.map((c, i) => {
    const prev = lay.clips[i - 1];
    const next = lay.clips[i + 1];
    const start = prev && prev.outEnd > c.outStart ? (prev.outEnd + c.outStart) / 2 : c.outStart;
    const end = next && c.outEnd > next.outStart ? (c.outEnd + next.outStart) / 2 : c.outEnd;
    return { start, end, transitionBefore: !!prev && prev.outEnd - c.outStart > 0.01 };
  });
}

/** Put a segment the AI cut out back on the timeline, next to the footage it came from, and forget the removal.
 *  The clip goes after the last clip of the same video that starts earlier in the source (else before the first
 *  one, else at the end), so the story keeps its original order. */
export function restoreRemoved(edl: Edl, index: number, mediaName = "Restored"): Edl {
  const r: RemovedSegment | undefined = edl.removed?.[index];
  if (!r) return edl;
  const mine = edl.clips.map((c, i) => ({ c, i })).filter((x) => x.c.mediaId === r.mediaId);
  const before = mine.filter((x) => x.c.srcStart < r.start);
  const at = before.length ? before[before.length - 1].i + 1 : mine.length ? mine[0].i : edl.clips.length;
  const clip = {
    id: uid("c"), mediaId: r.mediaId, srcStart: r3(r.start), srcEnd: r3(r.end), sceneBreak: true,
    label: `${mediaName.replace(/\.[^.]+$/, "")} · restored`, focusX: 0.5, focusY: 0.5, score: null,
    scoreBreakdown: null, rejected: false, boring: false, boringReason: null,
  };
  const clips = [...edl.clips];
  clips.splice(at, 0, clip);
  return { ...edl, clips, removed: (edl.removed ?? []).filter((_, i) => i !== index) };
}

export const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];

export function setClipSpeed(edl: Edl, clipId: string, speed: number): Edl {
  const v = r3(Math.min(4, Math.max(0.25, speed)));
  return { ...edl, clips: edl.clips.map((c) => (c.id === clipId && !c.freeze ? { ...c, speed: v } : c)) };
}

/** Insert a freeze frame (default 2 s) at output time `t` of the clip under it, splitting that clip around it. */
export function freezeFrameAt(edl: Edl, lay: Layout, t: number, clipId: string | null, mediaDuration: number, hold = 2): { edl: Edl; newId: string } | null {
  const target = lay.clips.find((c) => (clipId ? c.clip.id === clipId : true) && t >= c.outStart && t < c.outEnd);
  if (!target || target.clip.freeze) return null;
  const c = target.clip;
  const at = r3(Math.min(c.srcEnd - 0.1, c.srcStart + (t - target.outStart) * clipRate(c)));
  const frozen = {
    ...c, id: uid("c"), srcStart: at, srcEnd: r3(Math.min(mediaDuration, at + 0.1)), speed: 1, freeze: hold,
    sceneBreak: false, label: "Freeze frame", bgRemoval: null,
  };
  const before = at - c.srcStart >= MIN_CLIP ? { ...c, srcEnd: at } : null;
  const after = c.srcEnd - at >= MIN_CLIP ? { ...c, id: uid("c"), srcStart: at, sceneBreak: false } : null;
  const clips = [...edl.clips];
  clips.splice(target.index, 1, ...[before, frozen, after].filter(Boolean) as typeof clips);
  return { edl: { ...edl, clips }, newId: frozen.id };
}

export function setFreezeHold(edl: Edl, clipId: string, hold: number): Edl {
  const v = r3(Math.min(30, Math.max(0.1, hold)));
  return { ...edl, clips: edl.clips.map((c) => (c.id === clipId && c.freeze ? { ...c, freeze: v } : c)) };
}

/** Copy a clip and place the copy right after it. */
export function duplicateClip(edl: Edl, clipId: string): { edl: Edl; newId: string } | null {
  const i = edl.clips.findIndex((c) => c.id === clipId);
  if (i < 0) return null;
  const copy = { ...edl.clips[i], id: uid("c"), sceneBreak: true };
  const clips = [...edl.clips];
  clips.splice(i + 1, 0, copy);
  return { edl: { ...edl, clips }, newId: copy.id };
}
