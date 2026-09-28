import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchRunStatuses, fetchSeriesBatch } from "../apiSeries";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  sessionStorage.clear();
});

function mockFetch(body: unknown, status = 200) {
  const fn = vi.fn().mockResolvedValue({
    ok: status < 400, status, statusText: "err", json: () => Promise.resolve(body),
  });
  globalThis.fetch = fn as unknown as typeof fetch;
  return fn;
}

describe("fetchSeriesBatch", () => {
  it("POSTs every run in one request", async () => {
    sessionStorage.setItem("vmn_token", "tok");
    const body = { series: { a: { loss: [] } }, series_total: {}, missing: [] };
    const fn = mockFetch(body);
    const out = await fetchSeriesBatch("w", "root/svc", ["a", "b"], null, 1000);
    expect(out).toEqual(body);
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/v1/workspaces/w/apps/root-svc/series");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.headers.Authorization).toBe("Bearer tok");
    expect(JSON.parse(init.body)).toEqual({ verstrs: ["a", "b"], keys: null, max_points: 1000 });
  });

  it("rejects with the server's detail and status", async () => {
    mockFetch({ detail: "nope" }, 404);
    await expect(fetchSeriesBatch("w", "a", ["x"], null, 10)).rejects.toMatchObject({
      message: "nope", status: 404,
    });
  });
});

describe("fetchRunStatuses", () => {
  it("asks the list endpoint for just these runs and keys the rows by verstr", async () => {
    const fn = mockFetch({
      rows: [{ verstr: "a", status: "running", started_at: "2026-01-01T00:00:00Z" }], total: 1,
    });
    const out = await fetchRunStatuses("w", "app", ["a", "b"]);
    expect(out.a.status).toBe("running");
    const url = new URL(fn.mock.calls[0][0], "http://x");
    expect(url.pathname).toBe("/api/v1/workspaces/w/apps/app/experiments");
    expect(url.searchParams.get("q")).toBe('verstr in ("a", "b")');
    expect(url.searchParams.get("limit")).toBe("2");
  });

  it("accepts a plain list from older servers", async () => {
    mockFetch([{ verstr: "a", status: "succeeded" }]);
    const out = await fetchRunStatuses("w", "app", ["a"]);
    expect(out.a.status).toBe("succeeded");
  });
});
