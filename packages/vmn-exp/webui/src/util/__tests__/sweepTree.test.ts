import { describe, expect, it } from "vitest";
import type { ExperimentRow } from "../../types";
import { foldState, isPending, treeRows, type InnerRuns } from "../sweepTree";

const run = (verstr: string, extra: Partial<ExperimentRow> = {}) =>
  ({ verstr, depth: 0, children: [], parent: null, ...extra }) as unknown as ExperimentRow;

const outer = run("o", { children: ["a", "b"], kind: "outer" });
const a = run("a", { parent: "o", depth: 1 });
const b = run("b", { parent: "o", depth: 1 });
const lone = run("z");
const ids = (items: ReturnType<typeof treeRows>) =>
  items.map((r) => (isPending(r) ? `${r.state}:${r.parent}` : r.verstr));
const loaded = (rows: ExperimentRow[]) => (): InnerRuns => ({ rows, more: 0 });

describe("foldState", () => {
  it("starts every outer run shut, whatever its size, and expand= opens it", () => {
    const big = run("big", { children: Array.from({ length: 30 }, (_, i) => `c${i}`) });
    expect(foldState(outer, new Set())).toBe(true);
    expect(foldState(big, new Set())).toBe(true);
    expect(foldState(outer, new Set(["o"]))).toBe(false);
  });

  it("is null for a run without inner runs", () => {
    expect(foldState(lone, new Set(["z"]))).toBeNull();
  });
});

describe("treeRows", () => {
  it("lists only the top-level runs while every outer is shut", () => {
    expect(ids(treeRows([outer, lone], new Set(), loaded([a, b])))).toEqual(["o", "z"]);
  });

  it("puts an open outer's inner runs right under it", () => {
    expect(ids(treeRows([outer, lone], new Set(["o"]), loaded([a, b])))).toEqual(["o", "a", "b", "z"]);
  });

  it("folds a nested outer the same way", () => {
    const mid = run("a", { parent: "o", depth: 1, children: ["deep"], kind: "outer" });
    const deep = run("deep", { parent: "a", depth: 2 });
    const innerOf = (r: ExperimentRow): InnerRuns => ({ rows: r.verstr === "o" ? [mid, b] : [deep], more: 0 });
    expect(ids(treeRows([outer], new Set(["o"]), innerOf))).toEqual(["o", "a", "b"]);
    expect(ids(treeRows([outer], new Set(["o", "a"]), innerOf))).toEqual(["o", "a", "deep", "b"]);
  });

  it("shows one placeholder row while an open outer's inner runs load or fail", () => {
    expect(ids(treeRows([outer, lone], new Set(["o"]), () => "loading"))).toEqual(["o", "loading:o", "z"]);
    expect(ids(treeRows([outer], new Set(["o"]), () => "error"))).toEqual(["o", "error:o"]);
  });

  it("places the placeholder one level under its outer", () => {
    const [, pending] = treeRows([outer], new Set(["o"]), () => "loading");
    expect(isPending(pending) && pending.depth).toBe(1);
  });

  it("notes the inner runs left out past the fetched page", () => {
    const items = treeRows([outer], new Set(["o"]), () => ({ rows: [a], more: 7 }));
    expect(ids(items)).toEqual(["o", "a", "more:o"]);
    const more = items[2];
    expect(isPending(more) && more.count).toBe(7);
  });

  it("drops the inner runs *keep* rejects (the chart brush)", () => {
    const items = treeRows([outer], new Set(["o"]), loaded([a, b]), (r) => r.verstr !== "a");
    expect(ids(items)).toEqual(["o", "b"]);
  });

  it("never loops on a run that names itself as its own inner run", () => {
    const self = run("s", { children: ["s"] });
    expect(ids(treeRows([self], new Set(["s"]), loaded([self])))).toEqual(["s"]);
  });
});
