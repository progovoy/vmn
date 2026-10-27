import { describe, it, expect } from "vitest";
import { indexingText, appRunsText } from "../indexing";

describe("indexingText", () => {
  it("says how far a loading index is", () => {
    expect(indexingText({ loaded: 12000, total: 45386 })).toBe("indexing 12,000 / 45,386 runs");
  });
  it("copes with a total not known yet (the store still naming its runs)", () => {
    expect(indexingText({ loaded: 0, total: null })).toBe("indexing…");
    expect(indexingText({ loaded: 1500, total: null })).toBe("indexing 1,500 runs…");
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
