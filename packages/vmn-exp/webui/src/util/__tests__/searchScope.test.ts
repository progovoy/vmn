/** Plan 23 W11 (§3.5): search covers every run whatever the view; these
 *  links carry the same filter across the Jobs view, a job's Runs tab and
 *  All runs. */
import { describe, it, expect } from "vitest";
import { allRunsHref, hasSearch, matchLine, matchingRunsHref } from "../searchScope";

const F = { query: "metrics.loss < 0.2", search: "grid one", branch: "main" };

describe("searchScope", () => {
  it("a job's chip opens its Runs tab with the same filter", () => {
    const href = matchingRunsHref("/ws/w/app/a", "1.0.0-dev.r1", F);
    const [path, qs] = href.split("?");
    expect(path).toBe("/ws/w/app/a/run/1.0.0-dev.r1");
    const p = new URLSearchParams(qs);
    expect([p.get("tab"), p.get("q"), p.get("search"), p.get("branch")])
      .toEqual(["runs", F.query, F.search, "main"]);
  });

  it("search all runs goes to All runs with the filter, no scope", () => {
    const href = allRunsHref("/ws/w/app/a", { search: "x", archived: true });
    expect(href).toBe("/ws/w/app/a?view=all&search=x&archived=1");
  });

  it("empty parts are left out", () => {
    expect(allRunsHref("/b", { query: " ", search: "" })).toBe("/b?view=all");
  });

  it("hasSearch: text or a query, not a branch alone", () => {
    expect(hasSearch(F)).toBe(true);
    expect(hasSearch({ branch: "main" })).toBe(false);
    expect(hasSearch({ query: "  " })).toBe(false);
  });

  it("the result line counts jobs and runs", () => {
    expect(matchLine(3, 412)).toEqual({ found: "3 outer runs · 412 runs match", all: "show all 412 runs" });
    expect(matchLine(1, 1)).toEqual({ found: "1 outer run · 1 run matches", all: "show the 1 run" });
    expect(matchLine(0, 0)).toEqual({ found: "no runs match", all: null });
    expect(matchLine(2, 1903).found).toBe("2 outer runs · 1,903 runs match");
  });
});
