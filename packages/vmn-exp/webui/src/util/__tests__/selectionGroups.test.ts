/** Query groups in the app-wide selection: "Select all N matching" on a
 *  job's Runs tab adds the query itself (scope, q, status) beside the
 *  explicit picks instead of replacing them. */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { readPicks, subscribePicks, writePicks } from "../runSelection";
import {
  addQueryGroup, compareList, describeGroup, readGroups, selectExactly, summarizeSelection,
  type QueryGroup,
} from "../selectionGroups";

const group = (extra: Partial<QueryGroup> = {}): QueryGroup => ({
  scope: "J1", q: "", status: "failed", count: 4000, job: "J1", label: "hist-0012",
  members: [{ verstr: "a", job: "J1" }, { verstr: "b", job: "J1" }], ...extra,
});

beforeEach(() => sessionStorage.clear());

describe("adding a query group", () => {
  it("keeps the picks of other jobs", () => {
    writePicks("w", "a", [{ verstr: "x", job: "J2" }]);
    addQueryGroup("w", "a", group());
    expect(readPicks("w", "a").map((p) => p.verstr)).toEqual(["x"]);
    expect(readGroups("w", "a")).toEqual([group()]);
  });

  it("absorbs the explicit picks it covers, so they are not counted twice", () => {
    writePicks("w", "a", [{ verstr: "a", job: "J1" }, { verstr: "x", job: "J2" }]);
    addQueryGroup("w", "a", group());
    expect(readPicks("w", "a").map((p) => p.verstr)).toEqual(["x"]);
    expect(summarizeSelection(readPicks("w", "a"), readGroups("w", "a")).runs).toBe(4001);
  });

  it("replaces the group of the same scope and query", () => {
    addQueryGroup("w", "a", group());
    addQueryGroup("w", "a", group({ count: 12 }));
    addQueryGroup("w", "a", group({ status: "succeeded", count: 7 }));
    expect(readGroups("w", "a").map((g) => g.count)).toEqual([12, 7]);
  });

  it("tells the subscribers", () => {
    const heard = vi.fn();
    const off = subscribePicks(heard);
    addQueryGroup("w", "a", group());
    off();
    expect(heard).toHaveBeenCalled();
  });
});

describe("the selection's summary", () => {
  it("counts the explicit picks plus every group's count, over their jobs", () => {
    const picks = [{ verstr: "x", job: "J2" }, { verstr: "y", job: "J3" }, { verstr: "z", job: "J3" }];
    const sum = summarizeSelection(picks, [group(), group({ scope: "J4", job: "J4", count: 9 })]);
    expect(sum).toMatchObject({ runs: 4012, jobs: 4 });
    expect(sum.text).toBe("4,012 runs from 4 jobs");
  });
});

describe("a group's text", () => {
  it("names its count, job and query", () => {
    expect(describeGroup(group())).toBe("all 4,000 matching in hist-0012 (status = failed)");
    expect(describeGroup(group({ q: "metrics.loss < 1", status: "" })))
      .toBe("all 4,000 matching in hist-0012 (metrics.loss < 1)");
    expect(describeGroup(group({ q: "metrics.loss < 1" })))
      .toBe("all 4,000 matching in hist-0012 (metrics.loss < 1 and status = failed)");
    expect(describeGroup(group({ status: "" }))).toBe("all 4,000 matching in hist-0012");
  });
});

describe("what Compare takes", () => {
  it("is the explicit picks plus up to the top 10 runs of each group, in board order", () => {
    const members = Array.from({ length: 15 }, (_, i) => ({ verstr: `m${i}` }));
    const runs = compareList([{ verstr: "x" }], [group({ members })]);
    expect(runs).toEqual(["x", ...members.slice(0, 10).map((p) => p.verstr)]);
  });
});

describe("selecting exactly a list of runs", () => {
  it("keeps a group whose members all stay selected", () => {
    writePicks("w", "a", [{ verstr: "x" }]);
    addQueryGroup("w", "a", group());
    selectExactly("w", "a", ["x", "a", "b", "y"]);
    expect(readGroups("w", "a")).toHaveLength(1);
    expect(readPicks("w", "a").map((p) => p.verstr)).toEqual(["x", "y"]);
  });

  it("turns a group that lost a member back into explicit picks of the rest", () => {
    addQueryGroup("w", "a", group());
    selectExactly("w", "a", ["b"]);
    expect(readGroups("w", "a")).toEqual([]);
    expect(readPicks("w", "a")).toEqual([{ verstr: "b", job: "J1" }]);
  });
});
