import { describe, it, expect } from "vitest";
import { NONE_GROUP } from "../../apiGroups";
import type { ExperimentRow } from "../../types";
import { boardRows, groupItems, isGroupItem, type GroupedRows } from "../groupItems";

const row = (v: string): ExperimentRow => ({
  idx: 1, verstr: v, code_verstr: v, timestamp: null, note: null, branch: "main",
  base_version: "0.0.1", params: {}, metrics: {},
});
const counts = { total: 0, running: 0, waiting: 0, done: 0, failed: 0, stuck: 0 };
const group = (key: string, verstrs: string[], total = verstrs.length) => ({
  key, label: key, target: null, counts, aggregates: {}, verstrs, rows_total: total, rows_unfiltered: total,
});
const data = (groups: ReturnType<typeof group>[]): GroupedRows => ({
  rows: groups.flatMap((g) => g.verstrs.map(row)), total: 0, groups, total_groups: groups.length,
});
const shape = (items: ReturnType<typeof groupItems>) =>
  items.map((it) => (isGroupItem(it) ? `${it.item}:${"group" in it ? it.group.key : it.key}` : it.verstr));

describe("the grouped board's items (plan 22 G4)", () => {
  it("puts each group's header above its rows, in the payload's order", () => {
    const items = groupItems(data([group("a", ["a1", "a2"]), group("b", ["b1"])]), "parent", new Set());
    expect(shape(items)).toEqual(["group:a", "a1", "a2", "group:b", "b1"]);
  });

  it("leaves a closed group's rows out, and its +N more row too", () => {
    const items = groupItems(data([group("a", ["a1"], 5), group("b", ["b1"])]), "parent", new Set(["a"]));
    expect(shape(items)).toEqual(["group:a", "group:b", "b1"]);
    expect(items[0]).toMatchObject({ open: false, foldable: true });
  });

  it("adds a +N more row for the rows a group has not loaded", () => {
    const items = groupItems(data([group("a", ["a1", "a2"], 12)]), "branch", new Set(), new Map([["a", "loading"]]));
    expect(items[3]).toEqual({ item: "more", key: "a", remaining: 10, state: "loading" });
  });

  it("never folds the parent grouping's (no parent run) group", () => {
    const items = groupItems(data([group(NONE_GROUP, ["x"])]), "parent", new Set([NONE_GROUP]));
    expect(shape(items)).toEqual([`group:${NONE_GROUP}`, "x"]);
    expect(items[0]).toMatchObject({ open: true, foldable: false });
    expect(groupItems(data([group(NONE_GROUP, ["x"])]), "branch", new Set())[0]).toMatchObject({ foldable: true });
  });

  it("keeps only the rows *keep* passes, and the headers of groups with one", () => {
    const keep = (r: ExperimentRow) => r.verstr !== "b1";
    const items = groupItems(data([group("a", ["a1"]), group("b", ["b1"])]), "parent", new Set(), new Map(), keep);
    expect(shape(items)).toEqual(["group:a", "a1"]);
  });

  it("lists the rows on screen without the headers", () => {
    const items = groupItems(data([group("a", ["a1"], 3), group("b", ["b1"])]), "parent", new Set());
    expect(boardRows(items).map((r) => r.verstr)).toEqual(["a1", "b1"]);
  });

  it("names each header's loaded rows, the ones *keep* passes, whether the group is open or shut", () => {
    const d = data([group("a", ["a1", "a2"], 5), group("b", ["b1"])]);
    const heads = (items: ReturnType<typeof groupItems>) =>
      items.flatMap((it) => (isGroupItem(it) && it.item === "group" ? [it.rows] : []));
    expect(heads(groupItems(d, "parent", new Set(["a"])))).toEqual([["a1", "a2"], ["b1"]]);
    const keep = (r: ExperimentRow) => r.verstr !== "a2";
    expect(heads(groupItems(d, "parent", new Set(), new Map(), keep))).toEqual([["a1"], ["b1"]]);
  });
});
