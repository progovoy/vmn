import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api } from "../api";

const urlOf = (call: unknown[]) => new URL(call[0] as string, "http://x");

describe("api.facets", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify({
        branches: ["main"], metric_keys: ["loss"], param_keys: ["lr"], total: 3,
      }), { status: 200 })),
    );
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("asks the facets endpoint in the app's tag form", async () => {
    const f = await api.facets("w", "my/app");
    expect(urlOf(fetchMock.mock.calls[0]).pathname)
      .toBe("/api/v1/workspaces/w/apps/my-app/experiments-facets");
    expect(f.branches).toEqual(["main"]);
    expect(f.total).toBe(3);
  });

  it("never disables the browser cache, so ETag revalidation can answer 304", async () => {
    await api.facets("w", "app");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.cache).toBeUndefined();
  });
});
