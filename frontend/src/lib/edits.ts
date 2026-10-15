// Pure EDL edit operations used by the timeline. Each returns a new EDL (or the same one if nothing changed).
import type { Edl } from "../types";
import { uid } from "./format";
import type { Layout } from "./layout";

export const MIN_CLIP = 0.3;
const r3 = (v: number) => Math.round(v * 1000) / 1000;

/** Split the clip under output time `t` (or `clipId` if given). Both halves must be >= MIN_CLIP. */
export function splitAt(edl: Edl, lay: Layout, t: number, clipId?: string | null): { edl: Edl; newId: string } | null {
  const target = clipId
    ? lay.clips.find((c) => c.clip.id === clipId && t > c.outStart && t < c.outEnd)
    : [...lay.clips].reverse().find((c) => t > c.outStart && t < c.outEnd);
  if (!target) return null;
  const at = r3(target.clip.srcStart + (t - target.outStart));
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
