import { describe, it, expect } from "vitest";
import { lineDiff } from "../lineDiff";

describe("lineDiff", () => {
  it("marks kept, removed and added lines in order", () => {
    expect(lineDiff("a\nb\nc", "a\nx\nc\nd")).toEqual([
      { op: "same", text: "a" },
      { op: "del", text: "b" },
      { op: "add", text: "x" },
      { op: "same", text: "c" },
      { op: "add", text: "d" },
    ]);
  });

  it("is all-same for equal text", () => {
    expect(lineDiff("a\nb", "a\nb").every((l) => l.op === "same")).toBe(true);
  });
});
