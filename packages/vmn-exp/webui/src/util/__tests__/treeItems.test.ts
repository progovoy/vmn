/** Plan 28 N6: the tree's visible items, walked from the loaded children
 *  pages: a node unfolds when the reader opened it, else when the server
 *  says `open`; a parent still loading shows a loading row, one with more
 *  children than loaded a `+N more` row. */
import { describe, expect, it } from "vitest";
import type { TreeRow } from "../../apiTree";
import { cellText, treeItems, worstAttention, type TreePages } from "../treeItems";
import { job } from "./jobFixture";

const row = (verstr: string, extra: Partial<TreeRow> = {}): TreeRow => ({
  idx: 1, verstr, code_verstr: "1.0.0", timestamp: null, note: null, branch: null,
  base_version: null, metrics: {}, job: null, open: false, ...extra,
} as TreeRow);
const node = (verstr: string, extra: Partial<TreeRow> = {}) => row(verstr, { job: job(), children: ["x"], ...extra });

function pages(byParent: Record<string, { rows: TreeRow[]; total?: number }[]>): TreePages {
  return {
    count: (parent) => byParent[parent]?.length ?? 1,
    page: (parent, i) => {
      const p = byParent[parent]?.[i];
      return p && { rows: p.rows, total: p.total ?? p.rows.length };
    },
  };
}

const summary = (items: ReturnType<typeof treeItems>["items"]) => items.map((it) =>
  it.kind === "node" ? `${"  ".repeat(it.depth)}${it.row.verstr}${it.expandable ? (it.expanded ? " -" : " +") : ""}`
    : `${"  ".repeat(it.depth)}${it.kind}${it.kind === "more" ? ` ${it.remaining}` : ""}`);

describe("treeItems", () => {
  it("unfolds open nodes and folds the rest", () => {
    const { items, wanted } = treeItems("L", pages({
      L: [{ rows: [node("a"), node("b", { open: true }), row("c")] }],
      b: [{ rows: [row("b1"), row("b2")] }],
    }), new Map());
    expect(summary(items)).toEqual(["a +", "b -", "  b1", "  b2", "c"]);
    expect(wanted).toEqual(["L", "b"]);
  });

  it("a reader's choice beats the server's hint", () => {
    const { items, wanted } = treeItems("L", pages({
      L: [{ rows: [node("a"), node("b", { open: true })] }],
    }), new Map([["a", true], ["b", false]]));
    expect(summary(items)).toEqual(["a -", "  loading", "b +"]);
    expect(wanted).toEqual(["L", "a"]);
  });

  it("says how many children are not loaded yet", () => {
    const { items } = treeItems("L", pages({ L: [{ rows: [row("a"), row("b")], total: 5 }] }), new Map());
    expect(summary(items)).toEqual(["a", "b", "more 3"]);
  });

  it("numbers each node among its siblings", () => {
    const { items } = treeItems("L", pages({ L: [{ rows: [row("a"), row("b")], total: 4 }] }), new Map());
    const nodes = items.flatMap((it) => (it.kind === "node" ? [it] : []));
    expect(nodes.map((n) => [n.posinset, n.setsize])).toEqual([[1, 4], [2, 4]]);
  });
});

describe("worstAttention", () => {
  const entries = [
    { key: "slow", label: "slow", level: "warn" as const, count: 1, q: "x" },
    { key: "unstable", label: "unstable", level: "error" as const, count: 1, q: "y" },
  ];
  it("picks an error-level part before a bigger warning", () => {
    const r = node("a", { job: job({ attention: { slow: 9, unstable: 2 } }) });
    expect(worstAttention(r, entries)).toMatchObject({ key: "unstable", count: 2, level: "error" });
  });
  it("reads a leaf's own matches, and none when nothing matches", () => {
    expect(worstAttention(row("a", { attention: { slow: 1 } }), entries)).toMatchObject({ key: "slow" });
    expect(worstAttention(node("b", { job: job({ attention: { slow: 0 } }) }), entries)).toBeNull();
  });
});

describe("cellText", () => {
  const r = row("a", {
    metrics: { loss: 0.25 }, params: { lr: 0.01 }, tags: { health: "ok" },
    duration_sec: 125, duration_ratio: 3.14, queue_sec: 5,
  });
  it("reads metrics, params, tags and the duration columns", () => {
    expect(cellText(r, "m:loss")).toEqual(["loss", "0.25"]);
    expect(cellText(r, "p:lr")).toEqual(["lr", "0.01"]);
    expect(cellText(r, "t:health")).toEqual(["health", "ok"]);
    expect(cellText(r, "c:ratio")).toEqual(["vs siblings", "3.1×"]);
    expect(cellText(r, "c:duration")[0]).toBe("duration");
    expect(cellText(r, "m:missing")).toEqual(["missing", "—"]);
  });
});
