import { describe, it, expect } from "vitest";
import {
  EMPTY_FILTER, commitText, filterTokens, isPlainText, joinClauses, readClause,
  removeToken, splitConjuncts, stateFromValues,
} from "../filterTokens";

describe("splitConjuncts", () => {
  it("splits a top-level and, keeping quoted and parenthesized ands whole", () => {
    expect(splitConjuncts('metrics.loss < 0.5 and note ~ "a and b" and (x = 1 and y = 2)'))
      .toEqual(["metrics.loss < 0.5", 'note ~ "a and b"', "(x = 1 and y = 2)"]);
  });

  it("keeps a query with a top-level or as one clause (and binds tighter)", () => {
    expect(splitConjuncts("a = 1 or b = 2 and c = 3")).toEqual(["a = 1 or b = 2 and c = 3"]);
  });

  it("is empty for blank text", () => {
    expect(splitConjuncts("   ")).toEqual([]);
  });
});

describe("readClause", () => {
  it("reads a status equality in any quote, or bare", () => {
    expect(readClause('status = "failed"')).toEqual({ kind: "status", statuses: ["failed"] });
    expect(readClause("status == 'running'")).toEqual({ kind: "status", statuses: ["running"] });
    expect(readClause("status = stuck")).toEqual({ kind: "status", statuses: ["stuck"] });
  });

  it("reads a status membership test in display order", () => {
    expect(readClause('status in ("succeeded", "running")'))
      .toEqual({ kind: "status", statuses: ["running", "succeeded"] });
  });

  it("leaves an unknown status as a plain query clause", () => {
    expect(readClause('status = "bogus"')).toEqual({ kind: "query", clause: 'status = "bogus"' });
  });

  it("reads a branch equality and the text search clause", () => {
    expect(readClause('branch = "feat/x"')).toEqual({ kind: "branch", branch: "feat/x" });
    expect(readClause('text ~ "batch"')).toEqual({ kind: "search", text: "batch" });
  });

  it("keeps anything else verbatim", () => {
    expect(readClause("metrics.loss < 0.5")).toEqual({ kind: "query", clause: "metrics.loss < 0.5" });
  });
});

describe("isPlainText", () => {
  it("tells free text from a query", () => {
    expect(isPlainText("batch size 64")).toBe(true);
    expect(isPlainText("metrics.loss < 1")).toBe(false);
    expect(isPlainText('note ~ "x"')).toBe(false);
    expect(isPlainText('status in ("failed")')).toBe(false);
  });
});

describe("commitText", () => {
  it("turns free text into the search", () => {
    expect(commitText(EMPTY_FILTER, "  batch ")).toEqual({ ...EMPTY_FILTER, search: "batch" });
  });

  it("files each typed clause where its shortcut would have", () => {
    const next = commitText(EMPTY_FILTER, 'status = "failed" and branch = "main" and metrics.loss < 1');
    expect(next).toEqual({ statuses: ["failed"], branch: "main", search: "", clauses: ["metrics.loss < 1"] });
  });

  it("appends query clauses and never duplicates one", () => {
    const one = commitText(EMPTY_FILTER, "a = 1");
    expect(commitText(one, "a = 1 and b = 2").clauses).toEqual(["a = 1", "b = 2"]);
  });
});

describe("filterTokens", () => {
  it("shows one token per filter, as the clause that would type it", () => {
    const state = { statuses: ["running", "failed"] as const, branch: "main", search: "bat", clauses: ["x = 1"] };
    expect(filterTokens({ ...state, statuses: [...state.statuses] }, true).map((t) => t.text)).toEqual([
      'status in ("running", "failed")', 'branch = "main"', 'text ~ "bat"', "x = 1", "archived",
    ]);
    expect(filterTokens({ ...EMPTY_FILTER, statuses: ["failed"] }, false).map((t) => t.text))
      .toEqual(['status = "failed"']);
  });

  it("removes a token's filter", () => {
    const state = commitText(EMPTY_FILTER, 'status = "failed" and x = 1 and y = 2');
    const [status, x] = filterTokens(state, false);
    expect(removeToken(state, status).statuses).toEqual([]);
    expect(removeToken(state, x).clauses).toEqual(["y = 2"]);
  });
});

describe("URL values", () => {
  it("reads the URL's q, status, branch and search into one state", () => {
    expect(stateFromValues({ query: "a = 1 and b = 2", status: "failed,running", branch: "dev", search: "s" }))
      .toEqual({ statuses: ["running", "failed"], branch: "dev", search: "s", clauses: ["a = 1", "b = 2"] });
  });

  it("joins clauses back into q, parenthesizing an or", () => {
    expect(joinClauses(["a = 1 or b = 2", "c = 3"])).toBe("(a = 1 or b = 2) and c = 3");
    expect(joinClauses(["a = 1 or b = 2"])).toBe("a = 1 or b = 2");
  });
});
