import { describe, it, expect } from "vitest";
import { NONE_GROUP } from "../../apiGroups";
import type { ExperimentColumns, ExperimentRow } from "../../types";
import { runColor } from "../../util";
import type { BoardGroup } from "../groupItems";
import { NO_GROUP_COLOR, chartGroupKeys, chartGroups, loadedGroupKeys } from "../chartGroups";

const row = (v: string): ExperimentRow => ({
  idx: 1, verstr: v, code_verstr: v, timestamp: null, note: null, branch: "main",
  base_version: "0.0.1", params: {}, metrics: {},
});
const counts = { total: 0, running: 0, waiting: 0, done: 0, failed: 0, stuck: 0 };
const group = (key: string, verstrs: string[], extra: Partial<BoardGroup> = {}): BoardGroup => ({
  key, label: key, target: null, counts, aggregates: {}, verstrs, rows_total: verstrs.length, ...extra,
});
const sweep = group("s", ["a", "b"], {
  target: { verstr: "s", idx: 1, name: "sweep", status: "succeeded", tree_status: null, metrics: {} },
});

describe("the Charts tab's colours by group (plan 22 G7)", () => {
  it("gives each group the board's order a series colour, and the no-value group grey, last", () => {
    const keys = new Map([["a", "s"], ["b", "s"], ["c", NONE_GROUP], ["d", "t"]]);
    const g = chartGroups(["a", "b", "c", "d"].map(row), keys, [group(NONE_GROUP, ["c"], { label: "(no parent run)" }), sweep, group("t", ["d"])], "parent");
    expect(g.legend.map((e) => [e.label, e.color, e.count])).toEqual([
      ["sweep", runColor(0), 2], ["t", runColor(1), 1], ["(no parent run)", NO_GROUP_COLOR, 1],
    ]);
    expect(g.colorOf.get("a")).toBe(runColor(0));
    expect(g.colorOf.get("c")).toBe(NO_GROUP_COLOR);
  });

  it("colours groups the board has not loaded after the loaded ones, labelled as the server would", () => {
    const keys = new Map([["a", "s"], ["x", "main"], ["y", "dev"]]);
    const g = chartGroups(["y", "a", "x"].map(row), keys, [group("main", ["x"], { label: "branch = main" })], "branch");
    expect(g.legend.map((e) => [e.key, e.label])).toEqual([
      ["main", "branch = main"], ["dev", "branch = dev"], ["s", "branch = s"],
    ]);
    expect(g.colorOf.get("y")).toBe(runColor(1));
  });

  it("leaves a run with no known group uncoloured and out of the legend", () => {
    const g = chartGroups([row("a"), row("z")], new Map([["a", "s"]]), [sweep], "parent");
    expect(g.colorOf.has("z")).toBe(false);
    expect(g.legend.map((e) => e.key)).toEqual(["s"]);
  });

  it("reads each run's group from the columns' group:<field>, else from the loaded groups", () => {
    const data: ExperimentColumns = {
      verstrs: ["a", "b"], idx: [1, 2], columns: { "group:branch": ["main", NONE_GROUP] }, total: 2,
    };
    expect(chartGroupKeys(data, "branch")).toEqual(new Map([["a", "main"], ["b", NONE_GROUP]]));
    expect(chartGroupKeys({ ...data, columns: {} }, "branch")).toBeNull();
    expect(loadedGroupKeys([sweep, group("t", ["c"])])).toEqual(new Map([["a", "s"], ["b", "s"], ["c", "t"]]));
  });
});
