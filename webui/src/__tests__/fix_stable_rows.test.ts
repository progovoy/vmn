import { describe, it, expect } from "vitest";
import { keepIfUnchanged } from "../util/stableRows";

describe("keepIfUnchanged", () => {
  const rows = [{ verstr: "a", metrics: { loss: 0.1 } }];

  it("keeps the previous array when a poll brought identical rows", () => {
    const again = [{ verstr: "a", metrics: { loss: 0.1 } }];
    expect(keepIfUnchanged(rows, again)).toBe(rows);
  });

  it("takes the new array when anything changed", () => {
    const moved = [{ verstr: "a", metrics: { loss: 0.2 } }];
    expect(keepIfUnchanged(rows, moved)).toBe(moved);
  });

  it("takes the new array when there was none before", () => {
    expect(keepIfUnchanged(null, rows)).toBe(rows);
  });
});
