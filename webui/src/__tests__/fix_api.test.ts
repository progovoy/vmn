import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api } from "../api";
import { withSignal } from "../requestScope";

const ok = (body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));

const urlOf = (call: unknown[]) => new URL(call[0] as string, "http://x");

describe("api paging and abort", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => ok({ rows: [{ verstr: "a" }], total: 5000 }));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("experiments() always asks for a bounded page and exposes the total", async () => {
    const rows = await api.experiments("w", "my/app", "loss", "running", "metrics.x < 1");
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.pathname).toBe("/api/v1/workspaces/w/apps/my-app/experiments");
    expect(url.searchParams.get("limit")).toBe("200");
    expect(url.searchParams.get("offset")).toBe("0");
    expect(url.searchParams.get("sort")).toBe("loss");
    expect(url.searchParams.get("status")).toBe("running");
    expect(url.searchParams.get("q")).toBe("metrics.x < 1");
    expect(rows.map((r) => r.verstr)).toEqual(["a"]);
    expect(rows.total).toBe(5000);
  });

  it("experiments() tolerates a server that answers a plain list", async () => {
    fetchMock.mockImplementation(() => ok([{ verstr: "a" }, { verstr: "b" }]));
    const rows = await api.experiments("w", "app");
    expect(rows.total).toBe(2);
  });

  it("experimentsPaged() forwards offset, limit and filters", async () => {
    await api.experimentsPaged("w", "app", {
      offset: 200, limit: 200, sort: "acc", status: "failed", query: 'note ~ "x"',
    });
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.searchParams.get("offset")).toBe("200");
    expect(url.searchParams.get("limit")).toBe("200");
    expect(url.searchParams.get("sort")).toBe("acc");
    expect(url.searchParams.get("status")).toBe("failed");
    expect(url.searchParams.get("q")).toBe('note ~ "x"');
  });

  it("recentExperiments() asks for the newest N only, newest first", async () => {
    fetchMock.mockImplementation(() => ok({
      rows: [
        { verstr: "old", timestamp: "2026-01-01T00:00:00Z" },
        { verstr: "new", timestamp: "2026-01-03T00:00:00Z" },
      ],
      total: 2,
    }));
    const rows = await api.recentExperiments("w", "app", 20);
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.searchParams.get("last")).toBe("20");
    expect(url.searchParams.get("limit")).toBe("20");
    expect(rows.map((r) => r.verstr)).toEqual(["new", "old"]);
  });

  it("requests made inside withSignal carry that signal", async () => {
    const ctrl = new AbortController();
    await withSignal(ctrl.signal, () => api.experiments("w", "app"));
    expect(fetchMock.mock.calls[0][1].signal).toBe(ctrl.signal);
  });

  it("requests made outside withSignal carry no signal", async () => {
    await api.experiments("w", "app");
    expect(fetchMock.mock.calls[0][1].signal).toBeUndefined();
  });
});
