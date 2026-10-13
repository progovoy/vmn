import { describe, it, expect } from "vitest";
import { canShift, shiftColumn } from "../leaderboardColumns";

const IDS = ["check", "idx", "status", "experiment", "m:a", "m:b", "p:c", "when"];
const none = new Set<string>();

describe("shiftColumn", () => {
  it("swaps a column with its neighbour", () => {
    expect(shiftColumn(IDS, "m:b", -1, none)).toEqual(
      ["check", "idx", "status", "experiment", "m:b", "m:a", "p:c", "when"],
    );
    expect(shiftColumn(IDS, "p:c", 1, none)).toEqual(
      ["check", "idx", "status", "experiment", "m:a", "m:b", "when", "p:c"],
    );
  });

  it("leaves the order alone at an edge or next to a fixed column", () => {
    expect(shiftColumn(IDS, "m:a", -1, none)).toBe(IDS);
    expect(shiftColumn(IDS, "when", 1, none)).toBe(IDS);
    expect(shiftColumn(IDS, "idx", 1, none)).toBe(IDS);
  });

  it("never swaps a pinned column with an unpinned one", () => {
    const pinned = new Set(["m:a"]);
    expect(canShift(IDS, "m:a", 1, pinned)).toBe(false);
    expect(canShift(IDS, "m:b", -1, pinned)).toBe(false);
    expect(canShift(IDS, "m:b", 1, pinned)).toBe(true);
    expect(canShift(IDS, "experiment", 1, none)).toBe(false);
  });
});
