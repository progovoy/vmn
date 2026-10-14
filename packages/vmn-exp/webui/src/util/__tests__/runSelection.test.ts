/** The app-wide run selection (the tray): one list of picks per
 *  (workspace, app) in sessionStorage. */
import { describe, it, expect, beforeEach, vi } from "vitest";
import type { ExperimentRow } from "../../types";
import {
  SELECT_ALL_CAP, groupPicks, pickOf, readPicks, subscribePicks, summarizePicks, writePicks,
} from "../runSelection";

const row = (extra: Partial<ExperimentRow>): ExperimentRow => ({
  verstr: "0.0.1-dev.x", code_verstr: "0.0.1", timestamp: "", note: null, branch: "main",
  base_version: "0.0.1", params: {}, metrics: {}, status: "succeeded", ...extra,
} as ExperimentRow);

beforeEach(() => sessionStorage.clear());

describe("the stored selection", () => {
  it("is empty at first", () => {
    expect(readPicks("w", "a")).toEqual([]);
  });

  it("keeps one list per workspace and app, in sessionStorage", () => {
    writePicks("w", "a", [{ verstr: "v1" }]);
    writePicks("w", "b", [{ verstr: "v2" }]);
    expect(readPicks("w", "a").map((p) => p.verstr)).toEqual(["v1"]);
    expect(readPicks("w", "b").map((p) => p.verstr)).toEqual(["v2"]);
    expect(sessionStorage.length).toBe(2);
  });

  it("drops duplicates and caps the picks at the select-all cap", () => {
    const many = Array.from({ length: SELECT_ALL_CAP + 20 }, (_, i) => ({ verstr: `v${i}` }));
    writePicks("w", "a", [{ verstr: "v0" }, ...many]);
    const picks = readPicks("w", "a");
    expect(picks).toHaveLength(SELECT_ALL_CAP);
    expect(picks[0].verstr).toBe("v0");
    expect(picks[1].verstr).toBe("v1");
  });

  it("reads garbage as empty", () => {
    writePicks("w", "a", [{ verstr: "v1" }]);
    sessionStorage.setItem(sessionStorage.key(0)!, "{not json");
    expect(readPicks("w", "a")).toEqual([]);
  });

  it("tells subscribers of every write", () => {
    const seen = vi.fn();
    const stop = subscribePicks(seen);
    writePicks("w", "a", [{ verstr: "v1" }]);
    stop();
    writePicks("w", "a", []);
    expect(seen).toHaveBeenCalledTimes(1);
  });
});

describe("a pick's job", () => {
  it("is the row's root", () => {
    expect(pickOf(row({ verstr: "t1", root: "J", parent: "P", name: "trial", idx: 4 })))
      .toEqual({ verstr: "t1", job: "J", name: "trial", idx: 4 });
  });

  it("is the parent when the root is unknown", () => {
    expect(pickOf(row({ verstr: "t1", parent: "P" })).job).toBe("P");
  });

  it("is the run itself for a top-level job (it counts as one run)", () => {
    expect(pickOf(row({ verstr: "J", root: null, kind: "outer" })).job).toBe("J");
  });

  it("is none for a single top-level run", () => {
    expect(pickOf(row({ verstr: "s", root: null, kind: "single" })).job).toBeNull();
  });
});

describe("the tray's summary", () => {
  const picks = [
    { verstr: "a", job: "J1" }, { verstr: "b", job: "J1" }, { verstr: "c", job: "J2" },
    { verstr: "d", job: null }, { verstr: "e" },
  ];

  it("counts runs and the distinct known jobs", () => {
    expect(summarizePicks(picks)).toEqual({ runs: 5, jobs: 2, text: "5 runs from 2 outer runs" });
  });

  it("leaves the jobs out when none is known", () => {
    expect(summarizePicks([{ verstr: "a" }])).toEqual({ runs: 1, jobs: 0, text: "1 run" });
  });

  it("groups the picks by job, jobs first in pick order, then the runs of no job", () => {
    const groups = groupPicks(picks);
    expect(groups.map((g) => [g.job, g.picks.map((p) => p.verstr)])).toEqual([
      ["J1", ["a", "b"]], ["J2", ["c"]], [null, ["d", "e"]],
    ]);
  });

  it("names a job group after the job when it is a pick itself", () => {
    const groups = groupPicks([{ verstr: "J1", job: "J1", name: "grid" }, { verstr: "a", job: "J1" }]);
    expect(groups[0].label).toBe("grid");
    expect(groupPicks([{ verstr: "a", job: "J1" }])[0].label).toBe("J1");
  });
});
