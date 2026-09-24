import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, artifactUrl } from "../api";

const urlOf = (call: unknown[]) => new URL(call[0] as string, "http://x");
const ok = (body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));

describe("api.experimentsColumns", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => ok({ verstrs: ["a"], idx: [1], columns: { "metrics.loss": [0.1] }, total: 1 }));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("asks only for the given keys, with the leaderboard's filter", async () => {
    const out = await api.experimentsColumns("w", "my/app", ["metrics.loss", "params.lr"], {
      query: 'note ~ "x"', status: "failed", sort: "loss", order: "asc", archived: true, limit: 500,
    });
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.pathname).toBe("/api/v1/workspaces/w/apps/my-app/experiments-columns");
    expect(url.searchParams.get("keys")).toBe("metrics.loss,params.lr");
    expect(url.searchParams.get("q")).toBe('note ~ "x"');
    expect(url.searchParams.get("status")).toBe("failed");
    expect(url.searchParams.get("sort")).toBe("loss");
    expect(url.searchParams.get("order")).toBe("asc");
    expect(url.searchParams.get("archived")).toBe("1");
    expect(url.searchParams.get("limit")).toBe("500");
    expect(out.columns["metrics.loss"]).toEqual([0.1]);
  });

  it("leaves unset filters off the URL", async () => {
    await api.experimentsColumns("w", "app", []);
    const url = urlOf(fetchMock.mock.calls[0]);
    expect([...url.searchParams.keys()]).toEqual(["keys"]);
  });
});

describe("archived rows in the list", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => ok({ rows: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("passes archived=1 only when asked", async () => {
    await api.experimentsPaged("w", "app", { archived: true });
    expect(urlOf(fetchMock.mock.calls[0]).searchParams.get("archived")).toBe("1");
    await api.experimentsPaged("w", "app", {});
    expect(urlOf(fetchMock.mock.calls[1]).searchParams.has("archived")).toBe(false);
  });
});

describe("artifactUrl", () => {
  it("encodes each component of a nested artifact path", () => {
    expect(artifactUrl("w", "my-app", "0.0.1-dev.a", "plots/loss curve.png"))
      .toBe("/api/v1/workspaces/w/apps/my-app/experiments/0.0.1-dev.a/artifacts/plots/loss%20curve.png");
  });
});
