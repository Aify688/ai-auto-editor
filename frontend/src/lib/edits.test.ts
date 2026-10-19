import { describe, expect, it } from "vitest";
import { restoreRemoved } from "./edits";
import type { Edl, EdlClip } from "../types";

const clip = (id: string, mediaId: string, a: number, b: number): EdlClip => ({
  id, mediaId, srcStart: a, srcEnd: b, sceneBreak: true, label: id, focusX: 0.5, focusY: 0.5, score: null,
  scoreBreakdown: null, rejected: false, boring: false, boringReason: null,
});
const edl = (clips: EdlClip[], removed: Edl["removed"]) => ({ clips, removed, excluded: [] }) as unknown as Edl;

describe("restoreRemoved", () => {
  const removed = [{ mediaId: "A", start: 5, end: 8, reason: "silence", label: "Long silence" }];
  it("keeps story order: after the earlier clip of the same video", () => {
    const e = edl([clip("a1", "A", 0, 4), clip("b1", "B", 0, 3), clip("a2", "A", 9, 12)], removed);
    const out = restoreRemoved(e, 0, "talk.mp4");
    expect(out.clips.map((c) => c.id)[0]).toBe("a1");
    expect(out.clips.map((c) => c.mediaId)).toEqual(["A", "A", "B", "A"]);
    expect(out.clips[1]).toMatchObject({ mediaId: "A", srcStart: 5, srcEnd: 8 });
    expect(out.removed).toHaveLength(0);
  });
  it("goes before the first clip of the video when it came earlier in the source", () => {
    const e = edl([clip("b1", "B", 0, 3), clip("a2", "A", 9, 12)], removed);
    expect(restoreRemoved(e, 0).clips[1].srcStart).toBe(5);
  });
  it("appends when the video has no clips at all", () => {
    const e = edl([clip("b1", "B", 0, 3)], removed);
    const out = restoreRemoved(e, 0);
    expect(out.clips[out.clips.length - 1].mediaId).toBe("A");
  });
  it("ignores an unknown index", () => {
    const e = edl([clip("b1", "B", 0, 3)], removed);
    expect(restoreRemoved(e, 5)).toBe(e);
  });
});
