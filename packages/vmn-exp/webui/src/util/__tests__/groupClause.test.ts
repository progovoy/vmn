/** Plan 23 §3.4: a group too big to unfold opens as a filter; its clause is
 *  derived from the grouping and the group's key (until S7 serves `clause`). */
import { describe, it, expect } from "vitest";
import { NONE_GROUP } from "../../apiGroups";
import { addFilterClause, groupClause, BIG_GROUP } from "../groupClause";

describe("groupClause", () => {
  it("quotes a status, a branch and a failure signature", () => {
    expect(groupClause("status", "failed")).toBe('status = "failed"');
    expect(groupClause("branch", "main")).toBe('branch = "main"');
    expect(groupClause("failure_sig", 'oom "x"')).toBe(`failure_sig = 'oom "x"'`);
  });

  it("writes a param's number or boolean bare and its string quoted", () => {
    expect(groupClause("params.lr", "0.01")).toBe("params.lr = 0.01");
    expect(groupClause("params.layers", "-3")).toBe("params.layers = -3");
    expect(groupClause("params.cache", "true")).toBe("params.cache = true");
    expect(groupClause("params.opt", "adam")).toBe('params.opt = "adam"');
    expect(groupClause("tags.team", "nlp")).toBe('tags.team = "nlp"');
  });

  it("quotes a key with characters a bare name can't hold", () => {
    expect(groupClause("params.train/lr", "1")).toBe('params."train/lr" = 1');
  });

  it("asks for absence for the no-value group, and unescapes a doubled key", () => {
    expect(groupClause("params.lr", NONE_GROUP)).toBe("params.lr = null");
    expect(groupClause("params.opt", `${NONE_GROUP}${NONE_GROUP}x`)).toBe(`params.opt = "${NONE_GROUP}x"`);
  });

  it("gives up on text holding both quotes, and on a link grouping", () => {
    expect(groupClause("failure_sig", `a"b'c`)).toBeNull();
    expect(groupClause("parent", "0.0.1")).toBeNull();
  });

  it("unfolds groups of up to 50 runs", () => {
    expect(BIG_GROUP).toBe(50);
  });
});

describe("addFilterClause", () => {
  it("files a status clause as the status and any other clause into q", () => {
    expect(addFilterClause({ status: "", query: "", search: "", branch: "" }, 'status = "failed"'))
      .toEqual({ status: "failed", query: "", search: "", branch: "" });
    expect(addFilterClause({ status: "running", query: "metrics.loss < 1", search: "x", branch: "" }, "params.lr = 0.01"))
      .toEqual({ status: "running", query: "metrics.loss < 1 and params.lr = 0.01", search: "x", branch: "" });
  });

  it("keeps a clause already there once", () => {
    expect(addFilterClause({ query: "params.lr = 0.01" }, "params.lr = 0.01").query).toBe("params.lr = 0.01");
  });
});
