import { describe, it, expect } from "vitest";
import { runCountText } from "../BoardHead";

const base = { loading: false, filtered: false, loaded: 3, total: 3, shownTop: 3, loadedTop: 3 };

describe("runCountText", () => {
  it("says loading while the first page is on its way", () => {
    expect(runCountText({ ...base, loading: true })).toBe("loading runs…");
  });
  it("counts the whole board's top-level runs, plus inner ones", () => {
    expect(runCountText(base)).toBe("3 runs");
    expect(runCountText({ ...base, loaded: 5, total: 5 })).toBe("3 runs · 5 incl. inner");
  });
  it("reads N of M under a filter", () => {
    expect(runCountText({ ...base, filtered: true, total: 7, shownTop: 5 })).toBe("5 of 7 runs");
  });
});
