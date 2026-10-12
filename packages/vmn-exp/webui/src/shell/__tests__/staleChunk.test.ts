import { describe, it, expect } from "vitest";
import { isStaleChunk, watchStaleChunks } from "../staleChunk";

const preloadError = (payload: unknown) =>
  window.dispatchEvent(Object.assign(new Event("vite:preloadError", { cancelable: true }), { payload }));

describe("staleChunk", () => {
  it("marks the error Vite reports for a chunk that failed to load", () => {
    const stop = watchStaleChunks();
    const err = new Error("whatever the browser says");
    preloadError(err);
    stop();
    expect(isStaleChunk(err)).toBe(true);
  });

  it("leaves every other error unmarked, and stops listening when told", () => {
    const stop = watchStaleChunks();
    stop();
    const late = new Error("late");
    preloadError(late);
    expect(isStaleChunk(late)).toBe(false);
    expect(isStaleChunk(new Error("dynamically imported module"))).toBe(false);
    expect(isStaleChunk("string")).toBe(false);
    expect(isStaleChunk(null)).toBe(false);
  });
});
