import { describe, it, expect } from "vitest";
import { incompleteText } from "../indexing";

describe("incompleteText (plan 33 §2.2)", () => {
  it("says how far the load is and that the results are partial", () => {
    expect(incompleteText({ loaded: 120_000, total: 734_000 })).toBe("indexing 16% — results incomplete");
  });
  it("copes with a total not known yet, or none", () => {
    expect(incompleteText({ loaded: 1500, total: null })).toBe("indexing — results incomplete");
    expect(incompleteText({ loaded: 0, total: 0 })).toBe("indexing 0% — results incomplete");
  });
  it("says nothing once loaded", () => {
    expect(incompleteText(undefined)).toBe("");
  });
});
