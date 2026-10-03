import { describe, it, expect } from "vitest";
import { merge3, resolveText } from "../merge";

const base = "a\nb\nc\nd\ne";

describe("merge3", () => {
  it("is clean when nothing changed", () => {
    expect(merge3(base, base, base)).toMatchObject({ clean: true, text: base });
  });

  it("takes either side's lone edit", () => {
    expect(merge3(base, "a\nB\nc\nd\ne", base).text).toBe("a\nB\nc\nd\ne");
    expect(merge3(base, base, "a\nb\nc\nD\ne").text).toBe("a\nb\nc\nD\ne");
  });

  it("merges non-overlapping edits from both sides", () => {
    const r = merge3(base, "A\nb\nc\nd\ne", "a\nb\nc\nd\ne\nf");
    expect(r).toMatchObject({ clean: true, text: "A\nb\nc\nd\ne\nf" });
  });

  it("merges a deletion and a distant insertion", () => {
    expect(merge3(base, "a\nc\nd\ne", "a\nb\nc\nd\nx\ne").text).toBe("a\nc\nd\nx\ne");
  });

  it("accepts identical edits on both sides", () => {
    expect(merge3(base, "a\nX\nc\nd\ne", "a\nX\nc\nd\ne")).toMatchObject({ clean: true, text: "a\nX\nc\nd\ne" });
  });

  it("reports overlapping edits as a conflict hunk", () => {
    const r = merge3(base, "a\nT\nc\nd\ne", "a\nY\nc\nd\ne");
    expect(r.clean).toBe(false);
    expect(r.text).toBeUndefined();
    expect(r.chunks).toEqual([
      { kind: "ok", lines: ["a"] },
      { kind: "conflict", base: ["b"], theirs: ["T"], yours: ["Y"] },
      { kind: "ok", lines: ["c", "d", "e"] },
    ]);
  });

  it("resolveText applies per-hunk choices", () => {
    const r = merge3(base, "a\nT\nc\nd\nE", "a\nY\nc\nd\nE2");
    const conflicts = r.chunks.filter((c) => c.kind === "conflict").length;
    expect(conflicts).toBe(2);
    expect(resolveText(r.chunks, ["theirs", "yours"])).toBe("a\nT\nc\nd\nE2");
    expect(resolveText(r.chunks, ["both", "base"])).toBe("a\nT\nY\nc\nd\ne");
  });
});
