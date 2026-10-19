import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";

const reply = (body: string, init: { status?: number; type?: string }) =>
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: init.status ?? 200, headers: { "content-type": init.type ?? "application/json" } })));

afterEach(() => vi.unstubAllGlobals());

describe("API client never feeds HTML to the JSON parser", () => {
  it("returns parsed JSON for a good response", async () => {
    reply(JSON.stringify({ basis: "footage", tracks: [] }), {});
    expect(await api.musicRecommendations("p1")).toMatchObject({ basis: "footage" });
  });
  it("turns a 200 HTML page into a clear error instead of 'Unexpected token <'", async () => {
    reply("<!doctype html><html></html>", { type: "text/html; charset=utf-8" });
    const err = await api.musicRecommendations("p1").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).not.toMatch(/Unexpected token/);
    expect(err.message).toMatch(/restart it with \.\/start\.sh --restart/);
  });
  it("reports an HTML error page (404) the same way", async () => {
    reply("<html>nope</html>", { status: 404, type: "text/html" });
    const err = await api.musicRecommendations("p1").catch((e) => e);
    expect(err.status).toBe(404);
    expect(err.message).toMatch(/older version/);
  });
  it("shows the server's own message for JSON errors", async () => {
    reply(JSON.stringify({ detail: "Upload a video first." }), { status: 409 });
    expect(await api.musicRecommendations("p1").catch((e) => e.message)).toBe("Upload a video first.");
  });
  it("handles an unreachable server", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const err = await api.musicRecommendations("p1").catch((e) => e);
    expect(err.status).toBe(0);
    expect(err.message).toMatch(/Cannot reach the FrameFlow server/);
  });
  it("handles a body that claims to be JSON but is not", async () => {
    reply("{not json", {});
    expect(await api.musicRecommendations("p1").catch((e) => e.message)).toMatch(/could not read/);
  });
  it("rejects other content types", async () => {
    reply("hello", { type: "text/plain" });
    expect(await api.musicRecommendations("p1").catch((e) => e.message)).toMatch(/unexpected response/);
  });
});
