import { describe, it, expect } from "vitest";
import { indexingText, appRunsText, staleText } from "../indexing";

describe("indexingText", () => {
  it("says how far a loading index is", () => {
    expect(indexingText({ loaded: 12000, total: 45386 })).toBe("indexing 12,000 / 45,386 runs");
  });
  it("says nothing once loaded", () => {
    expect(indexingText(undefined)).toBe("");
  });
});

describe("appRunsText", () => {
  it("prefers the loading progress", () => {
    expect(appRunsText({ total: 500, indexing: { loaded: 500, total: 9000 } }, null)).toBe(
      "indexing 500 / 9,000 runs");
  });
  it("takes the status total, else the listed count", () => {
    expect(appRunsText({ total: 3 }, 7)).toBe("3 runs");
    expect(appRunsText(undefined, 7)).toBe("7 runs");
  });
  it("counts while neither is known", () => {
    expect(appRunsText(undefined, null)).toBe("counting runs…");
  });
});

describe("staleText", () => {
  const healthy = { alive: true, failing: false, failures: 0, since_refresh_sec: 1,
    refreshing_sec: null, last_error: null };
  it("says nothing of a fresh index, or without a background refresher", () => {
    expect(staleText({ refresher: healthy })).toBe("");
    expect(staleText({ refresher: { ...healthy, since_refresh_sec: 200 } })).toBe("");
    expect(staleText({})).toBe("");
    expect(staleText(undefined)).toBe("");
  });
  it("says how far behind a stale index is", () => {
    expect(staleText({ refresher: { ...healthy, since_refresh_sec: 44 * 60 + 5 } })).toBe(
      "index 44 min behind");
  });
  it("counts a refresh still running when none finished yet", () => {
    expect(staleText({ refresher: { ...healthy, since_refresh_sec: null, refreshing_sec: 900 } }))
      .toBe("index 15 min behind");
  });
  it("says a failing refresh fails before it falls a minute behind", () => {
    const failing = { ...healthy, failing: true, failures: 3, last_error: "RuntimeError('x')" };
    expect(staleText({ refresher: failing })).toBe("index refresh failing");
    expect(staleText({ refresher: { ...failing, since_refresh_sec: 180 } })).toBe(
      "index 3 min behind");
  });
  it("leaves a loading index to its progress", () => {
    expect(staleText({ indexing: { loaded: 1, total: 9 },
      refresher: { ...healthy, since_refresh_sec: null, refreshing_sec: 900 } })).toBe("");
  });
});
