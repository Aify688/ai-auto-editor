import { describe, expect, it } from "vitest";
import { generationState } from "./generation";

const base = { visualCount: 0, readyCount: 0, processing: false, instruction: "", running: false, hasEdit: false };

describe("generationState", () => {
  it("is disabled with neither media nor a description", () => {
    const s = generationState(base);
    expect(s.enabled).toBe(false);
    expect(s.mode).toBe("none");
    expect(s.reason).toMatch(/describe a video/);
  });
  it("treats whitespace as empty", () => {
    expect(generationState({ ...base, instruction: " \n\t " }).enabled).toBe(false);
  });
  it("enables text-to-video for a description alone", () => {
    const s = generationState({ ...base, instruction: "A fox in the snow" });
    expect(s).toMatchObject({ mode: "text", enabled: true, label: "Generate AI Video" });
  });
  it("enables auto edit for media alone", () => {
    const s = generationState({ ...base, visualCount: 2, readyCount: 2 });
    expect(s).toMatchObject({ mode: "edit", enabled: true, label: "Auto-edit" });
  });
  it("footage plus a description is an auto edit that follows the description", () => {
    expect(generationState({ ...base, visualCount: 1, readyCount: 1, instruction: "make it punchy" }).mode).toBe("edit");
  });
  it("disables while a request is running or media is processing", () => {
    expect(generationState({ ...base, instruction: "x", running: true }).enabled).toBe(false);
    expect(generationState({ ...base, visualCount: 1, processing: true }).enabled).toBe(false);
  });
  it("labels a repeat run", () => {
    expect(generationState({ ...base, visualCount: 1, readyCount: 1, hasEdit: true }).label).toBe("Auto-edit");
    expect(generationState({ ...base, instruction: "x", hasEdit: true }).label).toBe("Regenerate AI Video");
  });
});
