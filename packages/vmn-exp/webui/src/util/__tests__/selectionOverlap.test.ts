/** Explicit picks that a selected query also matches (counted once). */
import { describe, it, expect } from "vitest";
import type { RunPick } from "../runSelection";
import type { QueryGroup } from "../selectionGroups";
import { overlapCandidates, overlapQuery, verstrInQuery } from "../selectionOverlap";

const group = (over: Partial<QueryGroup> = {}): QueryGroup => ({
  scope: "J1", q: "loss < 1", status: "failed", count: 100, job: "J1", label: "grid", members: [], ...over,
});

describe("overlapCandidates", () => {
  it("takes the picks of the group's outer run, and those of no known outer run", () => {
    const picks: RunPick[] = [
      { verstr: "a", job: "J1" }, { verstr: "b", job: "J2" }, { verstr: "c" }, { verstr: "d", job: null },
    ];
    expect(overlapCandidates(group(), picks)).toEqual(["a", "c"]);
  });

  it("takes none when no pick is under the group's outer run", () => {
    expect(overlapCandidates(group(), [{ verstr: "b", job: "J2" }])).toEqual([]);
  });
});

describe("verstrInQuery", () => {
  it("quotes each verstr", () => {
    expect(verstrInQuery(["a.1", 'b"2'])).toBe('verstr in ("a.1", "b\\"2")');
  });
});

describe("overlapQuery", () => {
  it("ands the group's query with the picks", () => {
    expect(overlapQuery("loss < 1 or lr > 2", ["a", "b"])).toBe('(loss < 1 or lr > 2) and verstr in ("a", "b")');
  });

  it("is the picks alone for a group without a query", () => {
    expect(overlapQuery("", ["a"])).toBe('verstr in ("a")');
  });
});
