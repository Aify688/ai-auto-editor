import { describe, expect, it } from "vitest";
import { moveAudio, withAudioClips } from "../lib/timelineOps";
import type { AudioClip, Edl, ProjectDoc } from "../types";
import { useStore } from "./project";

const clip = (): AudioClip => ({ id: "a1", mediaId: "song", kind: "music", start: 1, trimIn: 0, duration: 4, volume: 0.5, fadeIn: 0, fadeOut: 0, loop: false, duck: true });
const doc = (): ProjectDoc => ({
  style: "cinematic", aspect: "16:9", settings: {} as ProjectDoc["settings"], export: {} as ProjectDoc["export"],
  edl: { clips: [], titles: [], captions: [], audioClips: [clip()], markers: [], music: null, transition: null } as unknown as Edl,
});
const startOf = () => useStore.getState().doc!.edl!.audioClips[0].start;

describe("undo / redo of timeline gestures", () => {
  it("a whole drag, however many pointer moves, is one undo step", () => {
    useStore.setState({ doc: doc(), past: [], future: [], coalesce: null });
    const key = `drag:audio:a1:${Date.now()}`;
    for (const delta of [0.5, 1.2, 2, 3]) {
      const moved = moveAudio(clip(), delta, { total: 20, points: [], pps: 100, others: [], srcDur: 10 }).clip;
      useStore.getState().updateDoc((d) => ({ ...d, edl: withAudioClips(d.edl!, [moved]) }), { coalesce: key });
    }
    expect(startOf()).toBe(4);
    expect(useStore.getState().past).toHaveLength(1);
    useStore.getState().undo();
    expect(startOf()).toBe(1);
    useStore.getState().redo();
    expect(startOf()).toBe(4);
  });
  it("two separate drags are two undo steps", () => {
    useStore.setState({ doc: doc(), past: [], future: [], coalesce: null });
    const move = (to: number, key: string) =>
      useStore.getState().updateDoc((d) => ({ ...d, edl: withAudioClips(d.edl!, [{ ...clip(), start: to }]) }), { coalesce: key });
    move(3, "drag:audio:a1:1");
    move(5, "drag:audio:a1:2");
    expect(useStore.getState().past).toHaveLength(2);
    useStore.getState().undo();
    expect(startOf()).toBe(3);
    useStore.getState().undo();
    expect(startOf()).toBe(1);
  });
  it("the legacy music mirror follows undo", () => {
    useStore.setState({ doc: doc(), past: [], future: [], coalesce: null });
    useStore.getState().updateDoc((d) => ({ ...d, edl: withAudioClips(d.edl!, []) }));
    expect(useStore.getState().doc!.edl!.music).toBeNull();
    useStore.getState().undo();
    expect(useStore.getState().doc!.edl!.audioClips).toHaveLength(1);
  });
});
