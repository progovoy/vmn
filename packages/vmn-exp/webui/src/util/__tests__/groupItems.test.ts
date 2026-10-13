import { describe, it, expect } from "vitest";
import { NONE_GROUP } from "../../apiGroups";
import type { ExperimentRow } from "../../types";
import { boardRows, groupItems, isGroupItem, memberPlaces, type GroupedRows } from "../groupItems";

const row = (v: string): ExperimentRow => ({
  idx: 1, verstr: v, code_verstr: v, timestamp: null, note: null, branch: "main",
  base_version: "0.0.1", params: {}, metrics: {},
});
const counts = { total: 0, running: 0, waiting: 0, done: 0, failed: 0, stuck: 0 };
const group = (key: string, verstrs: string[], total = verstrs.length, loose = false) => ({
  key, label: key, target: null, loose, counts, aggregates: {}, verstrs, rows_total: total, rows_unfiltered: total,
});
const loose = (verstrs: string[], total = verstrs.length) => group(NONE_GROUP, verstrs, total, true);
const data = (groups: ReturnType<typeof group>[]): GroupedRows => ({
  rows: groups.flatMap((g) => g.verstrs.map(row)), total: 0, groups, total_groups: groups.length,
});
const shape = (items: ReturnType<typeof groupItems>) =>
  items.map((it) => (isGroupItem(it) ? `${it.item}:${"group" in it ? it.group.key : it.key}` : it.verstr));

describe("the grouped board's items (plan 22 G4)", () => {
  it("puts each group's header above its rows, in the payload's order", () => {
    const items = groupItems(data([group("a", ["a1", "a2"]), group("b", ["b1"])]), new Set());
    expect(shape(items)).toEqual(["group:a", "a1", "a2", "group:b", "b1"]);
  });

  it("leaves a closed group's rows out, and its +N more row too", () => {
    const items = groupItems(data([group("a", ["a1"], 5), group("b", ["b1"])]), new Set(["a"]));
    expect(shape(items)).toEqual(["group:a", "group:b", "b1"]);
    expect(items[0]).toMatchObject({ open: false });
  });

  it("adds a +N more row for the rows a group has not loaded", () => {
    const items = groupItems(data([group("a", ["a1", "a2"], 12)]), new Set(), new Map([["a", "loading"]]));
    expect(items[3]).toEqual({ item: "more", key: "a", remaining: 10, state: "loading" });
  });

  it("gives a loose group no header: its rows, then its +N more row, follow the groups (plan 22 F12)", () => {
    const items = groupItems(data([group("a", ["a1"]), loose(["x", "y"], 5)]), new Set(), new Map([[NONE_GROUP, "error"]]));
    expect(shape(items)).toEqual(["group:a", "a1", "x", "y", `more:${NONE_GROUP}`]);
    expect(items[4]).toEqual({ item: "more", key: NONE_GROUP, remaining: 3, state: "error" });
  });

  it("never folds a loose group, whatever collapse= says, and keeps only the rows *keep* passes", () => {
    expect(shape(groupItems(data([loose(["x"])]), new Set([NONE_GROUP])))).toEqual(["x"]);
    const keep = (r: ExperimentRow) => r.verstr !== "x";
    expect(shape(groupItems(data([group("a", ["a1"]), loose(["x", "y"])]), new Set(), new Map(), keep)))
      .toEqual(["group:a", "a1", "y"]);
  });

  it("folds a (none) group that is not loose like any other", () => {
    const items = groupItems(data([group(NONE_GROUP, ["x"])]), new Set([NONE_GROUP]));
    expect(shape(items)).toEqual([`group:${NONE_GROUP}`]);
  });

  it("keeps only the rows *keep* passes, and the headers of groups with one", () => {
    const keep = (r: ExperimentRow) => r.verstr !== "b1";
    const items = groupItems(data([group("a", ["a1"]), group("b", ["b1"])]), new Set(), new Map(), keep);
    expect(shape(items)).toEqual(["group:a", "a1"]);
  });

  it("lists the rows on screen without the headers", () => {
    const items = groupItems(data([group("a", ["a1"], 3), group("b", ["b1"])]), new Set());
    expect(boardRows(items).map((r) => r.verstr)).toEqual(["a1", "b1"]);
  });

  it("names each header's loaded rows, the ones *keep* passes, whether the group is open or shut", () => {
    const d = data([group("a", ["a1", "a2"], 5), group("b", ["b1"])]);
    const heads = (items: ReturnType<typeof groupItems>) =>
      items.flatMap((it) => (isGroupItem(it) && it.item === "group" ? [it.rows] : []));
    expect(heads(groupItems(d, new Set(["a"])))).toEqual([["a1", "a2"], ["b1"]]);
    const keep = (r: ExperimentRow) => r.verstr !== "a2";
    expect(heads(groupItems(d, new Set(), new Map(), keep))).toEqual([["a1"], ["b1"]]);
  });
});

describe("where a group's members sit (plan 22 F11)", () => {
  const places = (items: ReturnType<typeof groupItems>) => {
    const at = memberPlaces(items);
    return items.map((it, i) => `${shape([it])[0]}${at.has(i) ? `:${at.get(i)}` : ""}`);
  };

  it("marks an open group's rows and +N more row, the last one last", () => {
    const items = groupItems(data([group("a", ["a1", "a2"], 4), group("b", ["b1"])]), new Set());
    expect(places(items)).toEqual(["group:a", "a1:mid", "a2:mid", "more:a:last", "group:b", "b1:last"]);
  });

  it("marks no loose row, nor its +N more row, though they follow a group's", () => {
    const items = groupItems(data([group("a", ["a1"]), loose(["x", "y"], 3)]), new Set());
    expect(places(items)).toEqual(["group:a", "a1:last", "x", "y", `more:${NONE_GROUP}`]);
  });

  it("marks no loose row after a shut group", () => {
    const items = groupItems(data([group("a", ["a1"]), loose(["x"])]), new Set(["a"]));
    expect(places(items)).toEqual(["group:a", "x"]);
  });
});
