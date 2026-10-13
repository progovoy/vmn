import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchGroupRows, fetchGroups, GROUP_AGGREGATES, NONE_GROUP } from "../apiGroups";
import type { GroupedPage, RunGroup } from "../apiGroups";

const urlOf = (call: unknown[]) => new URL(call[0] as string, "http://x");
const respond = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

const GROUP: RunGroup = {
  key: "0.1.0-dev.a.b.1", label: "0.1.0-dev.a.b.1",
  target: { verstr: "0.1.0-dev.a.b.1", idx: 4, name: "sweep", status: "succeeded",
            tree_status: "running", metrics: { loss: 0.91 } },
  counts: { total: 16, running: 2, waiting: 0, done: 13, failed: 1, stuck: 0 },
  aggregates: { loss: { mean: 0.5, best: 0.2, median: 0.45, min: 0.2, max: 0.9, n: 16 } },
  rows: [], rows_total: 16,
};

describe("apiGroups", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => respond({ groups: [], total_groups: 0, total_rows: 0 }));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("asks the list endpoint for groups with the board's filter", async () => {
    const page: GroupedPage = { groups: [GROUP], total_groups: 1, total_rows: 16 };
    fetchMock.mockImplementation(() => respond(page));
    const got = await fetchGroups("w", "root/svc", {
      group: "parent", agg: "best", sort: "loss", order: "asc", status: "running",
      query: "metrics.loss < 1", archived: true, offset: 50, limit: 25, rowsPerGroup: 5,
    });
    expect(got).toEqual(page);
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.pathname).toBe("/api/v1/workspaces/w/apps/root-svc/experiments");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      group: "parent", agg: "best", sort: "loss", order: "asc", status: "running",
      q: "metrics.loss < 1", archived: "1", offset: "50", limit: "25", rows_per_group: "5",
    });
  });

  it("leaves the aggregate to the app's default when none is picked", async () => {
    await fetchGroups("w", "app", { group: "params.lr" });
    const params = urlOf(fetchMock.mock.calls[0]).searchParams;
    expect(params.get("group")).toBe("params.lr");
    expect(params.has("agg")).toBe(false);
    expect(params.has("rows_per_group")).toBe(false);
    expect(params.get("offset")).toBe("0");
  });

  it("pages one group's rows by its key", async () => {
    fetchMock.mockImplementation(() => respond(GROUP));
    const got = await fetchGroupRows("w", "app", NONE_GROUP, {
      group: "parent", agg: "median", offset: 10, limit: 40,
    });
    expect(got.rows_total).toBe(16);
    const params = urlOf(fetchMock.mock.calls[0]).searchParams;
    expect(params.get("group_key")).toBe("(none)");
    expect(params.get("offset")).toBe("10");
    expect(params.get("limit")).toBe("40");
    expect(params.get("agg")).toBe("median");
  });

  it("names every aggregate the server takes, mean first (the default)", () => {
    expect(GROUP_AGGREGATES).toEqual(["mean", "best", "median", "min", "max"]);
  });
});
