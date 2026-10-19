import { describe, expect, it } from "vitest";
import type { AudioClip, Caption, Edl, Title } from "../types";
import type { CaptionSpan } from "./layout";
import {
  MIN_LEN, assignLanes, audioLength, duplicateAudio, duplicateCaption, duplicateTitle, laneOthers, moveAudio, moveCaption, moveTitle,
  primaryMusic, resetCaption, setPrimaryMusic, snapRange, snapValue, splitAudio, splitCaption, splitTitle,
  toggleMarker, trimAudioEnd, trimAudioStart, trimCaptionEnd, trimCaptionStart, trimTitleEnd, trimTitleStart,
} from "./timelineOps";

const clip = (o: Partial<AudioClip> = {}): AudioClip => ({
  id: "a1", mediaId: "song", kind: "music", start: 2, trimIn: 1, duration: 4, volume: 0.5, fadeIn: 0, fadeOut: 0, loop: false, duck: true, ...o,
});
const ctx = (o: Partial<Parameters<typeof moveAudio>[2]> = {}) => ({ total: 20, points: [] as number[], pps: 100, others: [], srcDur: 10, ...o });

describe("snapping", () => {
  it("snaps within 8 screen pixels and not beyond", () => {
    expect(snapValue(5.05, [5], 100)).toEqual({ value: 5, snapped: 5 });          // 5 px away at 100 px/s
    expect(snapValue(5.2, [5], 100).snapped).toBeNull();                          // 20 px away
    expect(snapValue(5.05, [5], 10).snapped).toBe(5);                             // zoomed out, same pixel distance is more time
  });
  it("snaps the closer edge of a range", () => {
    const r = snapRange(3.97, 2, [6], 100);                                       // end 5.97 is 3 px from 6
    expect(r.snapped).toBe(6);
    expect(r.start).toBeCloseTo(4, 5);
  });
});

describe("audio clip length", () => {
  it("is limited by the source without looping and by the video end always", () => {
    expect(audioLength(clip({ duration: null }), 10, 20)).toBe(9);                 // 10 s source - 1 s trim
    expect(audioLength(clip({ duration: 30 }), 10, 20)).toBe(9);
    expect(audioLength(clip({ duration: 30, loop: true }), 10, 20)).toBe(18);     // cut at the video end (20 - 2)
  });
});

describe("dragging an audio clip", () => {
  it("moves the body without changing its duration or source trim", () => {
    const { clip: c } = moveAudio(clip(), 3, ctx());
    expect(c.start).toBe(5);
    expect(c.duration).toBe(4);
    expect(c.trimIn).toBe(1);
  });
  it("never leaves the timeline", () => {
    expect(moveAudio(clip(), -10, ctx()).clip.start).toBe(0);
    const r = moveAudio(clip(), 100, ctx()).clip;
    expect(r.start + (r.duration ?? 0)).toBeLessThanOrEqual(20);
  });
  it("snaps to the playhead and to other clip edges", () => {
    expect(moveAudio(clip(), 1.97, ctx({ points: [4] })).snapped).toBe(4);       // start 3.97 -> 4
    expect(moveAudio(clip(), 1.97, ctx({ points: [4] })).clip.start).toBe(4);
  });
  it("cannot overlap or jump over a neighbour in the same lane", () => {
    const others = [{ start: 7, end: 9 }];
    const r = moveAudio(clip(), 5, ctx({ others })).clip;                         // wants start 7, end 11
    expect(r.start + (r.duration ?? 0)).toBeLessThanOrEqual(7 + 1e-6);
    const left = [{ start: 0, end: 1.5 }];
    expect(moveAudio(clip(), -5, ctx({ others: left })).clip.start).toBe(1.5);
  });
});

describe("trimming an audio clip", () => {
  it("left edge moves the in-point so the sound does not shift", () => {
    const { clip: c } = trimAudioStart(clip(), 1, ctx());                        // start 2 -> 3, trimIn 1 -> 2, end stays 6
    expect(c.start).toBe(3);
    expect(c.trimIn).toBe(2);
    expect(c.start + (c.duration ?? 0)).toBeCloseTo(6, 5);
  });
  it("left edge cannot go before the start of the source file or the timeline", () => {
    const c = trimAudioStart(clip({ trimIn: 1 }), -5, ctx()).clip;               // only 1 s of source is available before
    expect(c.trimIn).toBe(0);
    expect(c.start).toBe(1);
    expect(trimAudioStart(clip({ start: 0.5, trimIn: 3 }), -5, ctx()).clip.start).toBe(0);
  });
  it("keeps a minimum length", () => {
    const c = trimAudioStart(clip(), 50, ctx()).clip;
    expect(c.duration).toBeGreaterThanOrEqual(MIN_LEN - 1e-9);
    expect(trimAudioEnd(clip(), -50, ctx()).clip.duration).toBeGreaterThanOrEqual(MIN_LEN - 1e-9);
  });
  it("right edge stops at the end of the source unless looping", () => {
    const c = trimAudioEnd(clip({ duration: 4 }), 50, ctx()).clip;                // source: 10 - 1 = 9 s available
    expect(c.duration).toBe(9);
    const l = trimAudioEnd(clip({ duration: 4, loop: true }), 50, ctx()).clip;    // looping may run to the video end
    expect(l.duration).toBe(18);
  });
  it("right edge stops at the next clip", () => {
    expect(trimAudioEnd(clip(), 50, ctx({ others: [{ start: 8, end: 12 }] })).clip.duration).toBe(6);
  });
  it("edges snap too", () => {
    const r = trimAudioEnd(clip(), 0.97, ctx({ points: [7] }));                   // end 6.97 -> 7
    expect(r.snapped).toBe(7);
    expect(r.clip.duration).toBe(5);
  });
});

describe("audio split / duplicate", () => {
  it("split keeps the sound continuous across the cut", () => {
    const [a, b] = splitAudio(clip({ fadeIn: 1, fadeOut: 2 }), 4, { srcDur: 10, total: 20 })!;
    expect(a).toMatchObject({ start: 2, trimIn: 1, duration: 2, fadeIn: 1, fadeOut: 0 });
    expect(b).toMatchObject({ start: 4, trimIn: 3, duration: 2, fadeIn: 0, fadeOut: 2 });
    expect(b.id).not.toBe(a.id);
  });
  it("split of a looping clip continues the loop phase", () => {
    const [, b] = splitAudio(clip({ loop: true, trimIn: 8, duration: 9 }), 5, { srcDur: 10, total: 20 })!;   // region is 2 s long
    expect(b.trimIn).toBeCloseTo(9, 5);                                           // 3 s in = 1.5 loops -> 1 s into the 2nd pass
  });
  it("refuses to split too close to an edge", () => {
    expect(splitAudio(clip(), 2.1, { srcDur: 10, total: 20 })).toBeNull();
    expect(splitAudio(clip(), 20, { srcDur: 10, total: 20 })).toBeNull();
  });
  it("duplicate lands after the original, skips occupied space, or reports no room", () => {
    expect(duplicateAudio(clip(), { srcDur: 10, total: 20, others: [] })!.start).toBe(6);
    expect(duplicateAudio(clip(), { srcDur: 10, total: 20, others: [{ start: 6, end: 8 }] })!.start).toBe(8);
    expect(duplicateAudio(clip({ start: 15 }), { srcDur: 10, total: 20, others: [] })).toBeNull();
  });
  it("lane neighbours exclude the clip itself", () => {
    const o = laneOthers([clip(), clip({ id: "a2", start: 10 })], "a1", () => 10, 20);
    expect(o).toEqual([{ start: 10, end: 14 }]);
  });
});

const title = (o: Partial<Title> = {}): Title => ({ id: "t1", text: "Hi", start: 3, duration: 2, position: "center", ...o });
const tctx = { total: 20, points: [] as number[], pps: 100 };

describe("text clips", () => {
  it("move keeps the duration and stays inside the video", () => {
    expect(moveTitle(title(), 2, tctx).title).toMatchObject({ start: 5, duration: 2 });
    expect(moveTitle(title(), -9, tctx).title.start).toBe(0);
    expect(moveTitle(title(), 99, tctx).title.start).toBe(18);
  });
  it("edges change only the visible time", () => {
    expect(trimTitleStart(title(), -1, tctx).title).toMatchObject({ start: 2, duration: 3 });
    expect(trimTitleEnd(title(), 4, tctx).title).toMatchObject({ start: 3, duration: 6 });
    expect(trimTitleEnd(title(), -9, tctx).title.duration).toBeCloseTo(MIN_LEN, 5);
    expect(trimTitleStart(title(), 9, tctx).title.duration).toBeCloseTo(MIN_LEN, 5);
    expect(trimTitleEnd(title(), 99, tctx).title.start + trimTitleEnd(title(), 99, tctx).title.duration).toBe(20);
  });
  it("snap to the playhead", () => {
    expect(moveTitle(title(), 1.98, { ...tctx, points: [5] }).title.start).toBe(5);
    expect(trimTitleEnd(title(), 0.97, { ...tctx, points: [6] }).title.duration).toBe(3);
  });
  it("split and duplicate", () => {
    const [a, b] = splitTitle(title(), 4)!;
    expect([a.duration, b.start, b.duration]).toEqual([1, 4, 1]);
    expect(splitTitle(title(), 3.05)).toBeNull();
    const d = duplicateTitle(title(), 20);
    expect(d.start).toBe(5);
    expect(d.id).not.toBe("t1");
  });
  it("overlapping clips stack in rows instead of hiding each other", () => {
    const lanes = assignLanes([{ id: "a", start: 0, end: 4 }, { id: "b", start: 2, end: 6 }, { id: "c", start: 4, end: 8 }]);
    expect(lanes.get("a")).toBe(0);
    expect(lanes.get("b")).toBe(1);
    expect(lanes.get("c")).toBe(0);
  });
});

const caption = (o: Partial<Caption> = {}): Caption => ({
  id: "c1", mediaId: "v", srcStart: 4, srcEnd: 8, text: "one two three four", ...o,
  words: o.words === undefined ? [
    { word: "one", start: 4, end: 5 }, { word: "two", start: 5, end: 6 }, { word: "three", start: 6, end: 7 }, { word: "four", start: 7, end: 8 },
  ] : o.words,
});
const span = (c = caption()): CaptionSpan => ({ caption: c, outStart: 1, outEnd: 5, words: [], clipOutStart: 0, clipOutEnd: 10, srcLo: 4 });
const cctx = { points: [] as number[], pps: 100, others: [] as { start: number; end: number }[] };

describe("captions: manual timing keeps the transcript", () => {
  it("moving shifts the window and the words and remembers the original times", () => {
    const { caption: c } = moveCaption(span(), 2, cctx);
    expect([c.srcStart, c.srcEnd]).toEqual([6, 10]);
    expect(c.words![0]).toMatchObject({ word: "one", start: 6 });
    expect(c).toMatchObject({ manual: true, origStart: 4, origEnd: 8, wordShift: 2, text: "one two three four" });
  });
  it("resizing changes the window only, words stay as transcribed", () => {
    const c = trimCaptionEnd(span(), -1, cctx).caption;
    expect([c.srcStart, c.srcEnd]).toEqual([4, 7]);
    expect(c.words![3]).toMatchObject({ start: 7, end: 8 });
    const s = trimCaptionStart(span(), 1, cctx).caption;
    expect([s.srcStart, s.srcEnd]).toEqual([5, 8]);
  });
  it("Reset restores the transcript timing after any mix of edits", () => {
    let c = moveCaption(span(), 1.5, cctx).caption;
    c = trimCaptionEnd(span(c), 0.5, cctx).caption;
    const back = resetCaption(c);
    expect([back.srcStart, back.srcEnd, back.manual]).toEqual([4, 8, false]);
    expect(back.words!.map((w) => w.start)).toEqual([4, 5, 6, 7]);
    expect(resetCaption(caption())).toEqual(caption());                            // untouched captions are unchanged
  });
  it("stays inside its video clip and off its neighbours", () => {
    expect(moveCaption(span(), 50, cctx).start).toBe(6);                           // clip ends at 10, caption is 4 long
    expect(moveCaption(span(), -50, cctx).start).toBe(0);
    expect(moveCaption(span(), 50, { ...cctx, others: [{ start: 7, end: 9 }] }).start).toBe(3);
    expect(trimCaptionEnd(span(), 50, { ...cctx, others: [{ start: 7, end: 9 }] }).end).toBe(7);
  });
  it("snaps while dragging", () => {
    expect(moveCaption(span(), 0.98, { ...cctx, points: [2] }).start).toBe(2);
  });
  it("split divides the words at the playhead; duplicate copies after the original", () => {
    const [a, b] = splitCaption(span(), 3)!;                                       // out 3 -> source 6
    expect([a.text, b.text]).toEqual(["one two", "three four"]);
    expect([a.srcEnd, b.srcStart]).toEqual([6, 6]);
    expect(splitCaption(span(), 1.1)).toBeNull();
    const d = duplicateCaption({ ...span(), clipOutEnd: 20 }, [])!;
    expect([d.srcStart, d.srcEnd]).toEqual([8, 12]);
    expect(duplicateCaption({ ...span(), clipOutEnd: 8 }, [])).toBeNull();       // no room left in the clip
  });
  it("split without word timing divides the text", () => {
    const c = caption({ words: null });
    const [a, b] = splitCaption(span(c), 3)!;
    expect(a.text.split(" ").length + b.text.split(" ").length).toBe(4);
  });
});

describe("markers and the primary music clip", () => {
  it("toggle adds, removes near an existing marker, keeps order", () => {
    let m = toggleMarker([], 5);
    m = toggleMarker(m, 2);
    expect(m).toEqual([2, 5]);
    expect(toggleMarker(m, 5.03)).toEqual([2]);
  });
  it("setPrimaryMusic keeps the legacy mirror in step", () => {
    const base = { audioClips: [], music: null, markers: [] } as unknown as Edl;
    const added = setPrimaryMusic(base, { mediaId: "lib:happy", volume: 0.2 });
    expect(primaryMusic(added)).toMatchObject({ mediaId: "lib:happy", volume: 0.2, loop: true });
    expect(added.music).toEqual({ mediaId: "lib:happy", volume: 0.2, duck: true });
    const changed = setPrimaryMusic(added, { volume: 0.6 });
    expect(changed.audioClips).toHaveLength(1);
    expect(changed.music!.volume).toBe(0.6);
    const none = setPrimaryMusic(changed, null);
    expect([none.audioClips.length, none.music]).toEqual([0, null]);
  });
});
