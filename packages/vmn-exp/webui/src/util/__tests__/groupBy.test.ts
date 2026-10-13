import { describe, it, expect } from "vitest";
import {
  AGGREGATES, LINK_GROUPS, defaultGroup, groupFields, parseAggregate, parseGroup,
} from "../groupBy";

const facets = (extra = {}) => ({
  branches: ["main"], metric_keys: ["loss"], param_keys: ["lr", "opt", "seed"],
  tag_keys: ["team"], param_values: { lr: 3, opt: 2, seed: 21 }, parented: 0, total: 30,
  ...extra,
});

describe("the Group by vocabulary (plan 22 G2)", () => {
  it("offers the four links, labelled for people", () => {
    expect(LINK_GROUPS.map((l) => [l.value, l.label])).toEqual([
      ["parent", "parent run"], ["forked_from", "forked from"],
      ["rerun_of", "rerun of"], ["code_verstr", "same code"],
    ]);
  });

  it("offers branch, status, every tag key and the params with <= 20 values", () => {
    expect(groupFields(facets()).map((f) => f.value)).toEqual([
      "branch", "status", "tags.team", "params.lr", "params.opt",
    ]);
  });

  it("keeps a param at exactly 20 values and drops one at 21", () => {
    const got = groupFields(facets({ param_values: { lr: 20, opt: 21, seed: 21 } }));
    expect(got.map((f) => f.value)).toContain("params.lr");
    expect(got.map((f) => f.value)).not.toContain("params.opt");
  });

  it("offers only branch and status before the facets arrive", () => {
    expect(groupFields(null).map((f) => f.value)).toEqual(["branch", "status"]);
  });

  it("defaults to the parent run when the app has parented runs, else none", () => {
    expect(defaultGroup(facets({ parented: 4 }))).toBe("parent");
    expect(defaultGroup(facets())).toBe("none");
  });

  it("reads a URL group: links, fields, keyed fields and none; anything else is unknown", () => {
    for (const g of ["none", "parent", "forked_from", "rerun_of", "code_verstr",
      "branch", "status", "tags.team", "params.lr"]) {
      expect(parseGroup(g)).toBe(g);
    }
    for (const g of ["", "inputs", "tags.", "params.", "metrics.loss", "kind"]) {
      expect(parseGroup(g)).toBeNull();
    }
    expect(parseGroup(null)).toBeNull();
  });

  it("knows the five aggregates, mean first", () => {
    expect(AGGREGATES).toEqual(["mean", "best", "median", "min", "max"]);
    expect(parseAggregate("best")).toBe("best");
    expect(parseAggregate("sum")).toBeNull();
    expect(parseAggregate(null)).toBeNull();
  });
});
