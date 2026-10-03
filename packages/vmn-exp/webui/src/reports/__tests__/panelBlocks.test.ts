import { describe, it, expect } from "vitest";
import { parse } from "yaml";
import { findPanelBlocks, insertPanelBlock, replacePanelBlock, specToBlock, queryProblem } from "../panelBlocks";

const SRC = "# T\n\n```vmn-panel\nv: 1\nid: a\n```\n\ntext\n\n```vmn-panel\nv: 1\nid: b\n```\n";

describe("panelBlocks", () => {
  it("finds fenced panel blocks with their raw yaml", () => {
    expect(findPanelBlocks(SRC).map((b) => b.raw)).toEqual(["v: 1\nid: a\n", "v: 1\nid: b\n"]);
  });

  it("serializes a spec into a fenced block", () => {
    const block = specToBlock({ v: 1, id: "x", type: "bar", app: "a", runs: { query: "status = succeeded" }, metric: "m" });
    expect(block.startsWith("```vmn-panel\n")).toBe(true);
    expect(block.endsWith("```\n")).toBe(true);
    expect(parse(block.slice(13, -4))).toMatchObject({ id: "x", runs: { query: "status = succeeded" } });
  });

  it("inserts a block at the caret on its own lines", () => {
    expect(insertPanelBlock("ab", 1, { v: 1, id: "x" })).toBe("a\n\n```vmn-panel\nv: 1\nid: x\n```\n\nb");
  });

  it("replaces the block whose raw text matches, leaving others", () => {
    const out = replacePanelBlock(SRC, "v: 1\nid: b\n", { v: 1, id: "b", type: "run" });
    const blocks = findPanelBlocks(out);
    expect(blocks[0].raw).toBe("v: 1\nid: a\n");
    expect(parse(blocks[1].raw)).toEqual({ v: 1, id: "b", type: "run" });
    expect(out.startsWith("# T\n\n")).toBe(true);
    expect(out.endsWith("```\n")).toBe(true);
  });

  it("flags unbalanced queries", () => {
    expect(queryProblem("a = 1")).toBeNull();
    expect(queryProblem("(a = 1")).toMatch(/parenthes/);
    expect(queryProblem('a = "x')).toMatch(/quote/);
    expect(queryProblem("  ")).toMatch(/empty/);
  });
});
