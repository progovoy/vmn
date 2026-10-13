import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api } from "../api";
import { NONE_GROUP, type GroupedPage } from "../apiGroups";

const urlOf = (call: unknown[]) => new URL(call[0] as string, "http://x");

/** A K1 answer (plan 22 §2), as the S1 endpoint builds it. */
const K1: GroupedPage = {
  groups: [{
    key: "0.0.1-dev.a", label: "sweep",
    target: {
      verstr: "0.0.1-dev.a", idx: 1, name: "sweep", status: "succeeded",
      tree_status: "running", metrics: { loss: 0.9 },
    },
    counts: { total: 2, running: 1, waiting: 0, done: 1, failed: 0, stuck: 0 },
    aggregates: { loss: { mean: 0.5, best: 0.4, median: 0.5, min: 0.4, max: 0.6, n: 2 } },
    rows: [], rows_total: 2, rows_unfiltered: 2, loose: false,
  }, {
    key: NONE_GROUP, label: "(none)", target: null, loose: true,
    counts: { total: 1, running: 0, waiting: 0, done: 1, failed: 0, stuck: 0 },
    aggregates: { loss: { mean: 1, best: null, median: 1, min: 1, max: 1, n: 1 } },
    rows: [], rows_total: 1, rows_unfiltered: 1,
  }],
  total_groups: 2, total_rows: 3, aggregate: "mean", running: 1,
};

describe("api.experimentGroups (plan 22 K1)", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify(K1), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("asks the list endpoint with group= and the filter, paging groups", async () => {
    const got = await api.experimentGroups("w", "my/app", {
      group: "parent", sort: "loss", order: "asc", status: "running", query: "lr > 1",
      archived: true, offset: 50, limit: 50,
    });
    expect(got).toEqual(K1);
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.pathname).toBe("/api/v1/workspaces/w/apps/my-app/experiments");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      group: "parent", sort: "loss", order: "asc", status: "running", q: "lr > 1",
      archived: "1", offset: "50", limit: "50",
    });
  });

  it("sends agg= and rows_per_group only when set (the server's conf default otherwise)", async () => {
    await api.experimentGroups("w", "app", { group: "branch" });
    expect(Object.fromEntries(urlOf(fetchMock.mock.calls[0]).searchParams))
      .toEqual({ group: "branch", offset: "0" });
    await api.experimentGroups("w", "app", { group: "branch", agg: "best", rowsPerGroup: 25 });
    const p = urlOf(fetchMock.mock.calls[1]).searchParams;
    expect(p.get("agg")).toBe("best");
    expect(p.get("rows_per_group")).toBe("25");
  });

  it("pages one group's rows with group_key", async () => {
    await api.experimentGroupRows("w", "app", "0.0.1-dev.a", { group: "parent", offset: 10, limit: 100 });
    const p = urlOf(fetchMock.mock.calls[0]).searchParams;
    expect(p.get("group_key")).toBe("0.0.1-dev.a");
    expect(p.get("offset")).toBe("10");
    expect(p.get("limit")).toBe("100");
  });
});
