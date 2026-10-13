import { describe, expect, it } from "vitest";
import type { DiffDelta } from "../../types";
import { deltaTone, fmtDelta, numericChange } from "../diffDeltaTone";

const dd = (from: unknown, to: unknown, goal: DiffDelta["goal"] = null, param = false) =>
  ({ from, to, goal, param }) as DiffDelta;

describe("diff delta tone", () => {
  it("is better/worse by the goal, flat without a goal, a change or for params", () => {
    expect(deltaTone(dd(1, 2, "max"), 1)).toBe("better");
    expect(deltaTone(dd(2, 1, "max"), -1)).toBe("worse");
    expect(deltaTone(dd(2, 1, "min"), -1)).toBe("better");
    expect(deltaTone(dd(1, 2), 1)).toBe("flat");
    expect(deltaTone(dd(1, 1, "max"), 0)).toBe("flat");
    expect(deltaTone(dd("a", "b", "max"), null)).toBe("flat");
    expect(deltaTone(dd(1, 2, "max", true), 1)).toBe("flat");
  });
  it("computes numeric changes and formats them signed", () => {
    expect(numericChange(dd(1, 3))).toBe(2);
    expect(numericChange(dd("x", 3))).toBeNull();
    expect(fmtDelta(2)).toBe("+2");
    expect(fmtDelta(null)).toBe("–");
  });
});
