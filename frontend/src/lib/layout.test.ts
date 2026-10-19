import { describe, expect, it } from "vitest";
import type { Edl, EdlClip } from "../types";
import { deleteClip, displayBounds, duplicateClip, freezeFrameAt, moveClip, setClipSpeed, splitAt, trimClip } from "./edits";
import { addKeyframe, valuesAt } from "./keyframes";
import { clipFilterCss, clipFlip, scaleCss } from "./effects";
import fixture from "./layout.fixture.json";
import { captionSpans, cropOffset, layout } from "./layout";

const clip = (id: string, mediaId: string, a: number, b: number, sceneBreak = true): EdlClip => ({
  id, mediaId, srcStart: a, srcEnd: b, sceneBreak, label: id, focusX: 0.5, focusY: 0.5, score: null,
  scoreBreakdown: null, rejected: false, boring: false, boringReason: null,
});
const edl = (clips: EdlClip[], transition: Edl["transition"] = null) => ({ clips, transition }) as unknown as Edl;

describe("layout", () => {
  it("matches the Python layout exactly (fixture written by tests/test_frameflow.py)", () => {
    const out = layout({ clips: fixture.clips as EdlClip[], transition: fixture.transition });
    expect(out.duration).toBe(fixture.expected.duration);
    expect(out.transition).toBe(fixture.expected.transition);
    expect(out.clips.map((c) => [c.outStart, c.outEnd])).toEqual(fixture.expected.clips.map((c) => [c.outStart, c.outEnd]));
  });

  it("hard cuts are sequential", () => {
    const out = layout(edl([clip("a", "m", 0, 2), clip("b", "m", 5, 6)]));
    expect(out.duration).toBe(3);
    expect(out.clips[1].outStart).toBe(2);
  });

  it("maps source-time captions through cuts", () => {
    const e = edl([clip("a", "m", 0, 2), clip("b", "m", 5, 7)]);
    const spans = captionSpans([{ id: "c", mediaId: "m", srcStart: 1.5, srcEnd: 5.5, text: "hi" }], layout(e).clips);
    expect(spans.map((s) => [s.outStart, s.outEnd])).toEqual([[1.5, 2], [2, 2.5]]);
  });

  it("crop offset keeps a right-side subject in a portrait crop", () => {
    expect(cropOffset(0.9, 0.5, 1920, 1080, "9:16")[0]).toBe(1);
    expect(cropOffset(0.5, 0.5, 1920, 1080, "9:16")).toEqual([0.5, 0.5]);
    expect(cropOffset(0.9, 0.5, 1080, 1080, "1:1")).toEqual([0.5, 0.5]);
  });
});

describe("edits", () => {
  const base = edl([clip("a", "m", 0, 4), clip("b", "n", 0, 3)]);

  it("splits at the playhead into a continuous hard cut", () => {
    const res = splitAt(base, layout(base), 1.5)!;
    expect(res.edl.clips.map((c) => [c.srcStart, c.srcEnd])).toEqual([[0, 1.5], [1.5, 4], [0, 3]]);
    expect(res.edl.clips[1].sceneBreak).toBe(false);
    expect(layout(res.edl).duration).toBe(layout(base).duration);
    expect(splitAt(base, layout(base), 0.1)).toBeNull();
  });

  it("deletes, moves and trims within media bounds", () => {
    expect(deleteClip(base, "a").clips.map((c) => c.id)).toEqual(["b"]);
    expect(moveClip(base, 0, 2).clips.map((c) => c.id)).toEqual(["b", "a"]);
    expect(trimClip(base, "a", "end", 99, 5).clips[0].srcEnd).toBe(5);
    expect(trimClip(base, "a", "start", 3.9, 5).clips[0].srcStart).toBe(3.7);
  });

  it("display bounds split transition overlaps at the midpoint", () => {
    const e = edl([clip("a", "m", 0, 3), clip("b", "n", 0, 3)], { type: "fade", duration: 1 });
    const b = displayBounds(layout(e));
    expect(b[0].end).toBe(b[1].start);
    expect(b[1].transitionBefore).toBe(true);
  });
});

describe("speed, freeze and keyframes", () => {
  it("a 2x clip is half as long and captions follow it", () => {
    const e = edl([{ ...clip("a", "m", 0, 4), speed: 2 }, clip("b", "m", 10, 11)]);
    const lay = layout(e);
    expect(lay.duration).toBe(3);
    expect(lay.clips[1].outStart).toBe(2);
    const spans = captionSpans([{ id: "c", mediaId: "m", srcStart: 1, srcEnd: 3, text: "hi" }], lay.clips);
    expect(spans.map((s) => [s.outStart, s.outEnd])).toEqual([[0.5, 1.5]]);
  });

  it("splitting a sped-up clip cuts at the right source time", () => {
    const e = edl([{ ...clip("a", "m", 0, 4), speed: 2 }]);
    const res = splitAt(e, layout(e), 1, "a")!;
    expect(res.edl.clips.map((c) => [c.srcStart, c.srcEnd])).toEqual([[0, 2], [2, 4]]);
  });

  it("setClipSpeed clamps, freeze frame splits the clip around a held frame", () => {
    const e = edl([clip("a", "m", 0, 4)]);
    expect(setClipSpeed(e, "a", 10).clips[0].speed).toBe(4);
    const res = freezeFrameAt(e, layout(e), 2, "a", 30)!;
    expect(res.edl.clips.map((c) => [c.srcStart, c.srcEnd, c.freeze ?? null])).toEqual([[0, 2, null], [2, 2.1, 2], [2, 4, null]]);
    expect(layout(res.edl).duration).toBe(6);
    expect(duplicateClip(res.edl, "a")?.edl.clips).toHaveLength(4);
  });

  it("interpolates keyframes linearly and with smooth easing", () => {
    const kfs = [
      { t: 0, scale: 1, x: 0, y: 0, rotation: 0, opacity: 1 },
      { t: 2, scale: 2, x: 0.2, y: 0, rotation: 10, opacity: 0, ease: "smooth" as const },
    ];
    expect(valuesAt(kfs, 1).scale).toBe(1.5);
    expect(valuesAt(kfs, 5).opacity).toBe(0);
    expect(valuesAt([{ ...kfs[0], ease: "smooth" }, kfs[1]], 0.5).scale).toBeCloseTo(1.15625, 5);
    expect(addKeyframe(kfs, 1, 2).map((k) => k.t)).toEqual([0, 1, 2]);
  });
});

describe("effects library", () => {
  it("scales a filter toward neutral by strength", () => {
    expect(scaleCss("contrast(1.2) hue-rotate(20deg)", 0.5)).toBe("contrast(1.1) hue-rotate(10deg)");
    expect(scaleCss("grayscale(1)", 1)).toBe("grayscale(1)");
  });
  it("builds the preview filter from a clip's filter and effects", () => {
    expect(clipFilterCss({ id: "bw", strength: 1 }, [{ id: "blur", amount: 0 }])).toBe("grayscale(1) contrast(1.1) blur(1px)");
    expect(clipFilterCss(null, [{ id: "vignette", amount: 1 }])).toBe("");
    expect(clipFlip([{ id: "flip_h", amount: 1 }])).toBe("scale(-1, 1)");
  });
});
