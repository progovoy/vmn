import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { runSimilar, textSimilar } from "../apiSimilar";

const urlOf = (call: unknown[]) => new URL(call[0] as string, "http://x");
const EMPTY = { items: [], truncated: false };

describe("apiSimilar", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify(EMPTY), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("asks for a run's similar runs under its app tag", async () => {
    expect(await runSimilar("w", "my/app", "0.0.1-dev.a b")).toEqual(EMPTY);
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.pathname).toBe("/api/v1/workspaces/w/apps/my-app/experiments/0.0.1-dev.a%20b/similar");
    expect([...url.searchParams.keys()]).toEqual([]);
  });

  it("sends top and all_apps only when set", async () => {
    await runSimilar("w", "app", "v", { top: 5, allApps: true });
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.searchParams.get("top")).toBe("5");
    expect(url.searchParams.get("all_apps")).toBe("1");
  });

  it("sends a free text to the app's text route", async () => {
    await textSimilar("w", "my/app", "focal loss & smoothing", { allApps: true });
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.pathname).toBe("/api/v1/workspaces/w/apps/my-app/similar");
    expect(url.searchParams.get("text")).toBe("focal loss & smoothing");
    expect(url.searchParams.get("all_apps")).toBe("1");
  });
});
