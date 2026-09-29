import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api } from "../api";

const urlOf = (call: unknown[]) => new URL(call[0] as string, "http://x");

describe("api.experimentsImportance", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify([]), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("asks for the metric under the leaderboard's filter", async () => {
    await api.experimentsImportance("w", "my/app", "loss", {
      query: "params.lr > 0", status: "failed", archived: true,
    });
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.pathname).toBe("/api/v1/workspaces/w/apps/my-app/experiments-importance");
    expect(url.searchParams.get("metric")).toBe("loss");
    expect(url.searchParams.get("q")).toBe("params.lr > 0");
    expect(url.searchParams.get("status")).toBe("failed");
    expect(url.searchParams.get("archived")).toBe("1");
  });

  it("leaves unset filters off the URL", async () => {
    await api.experimentsImportance("w", "app", "acc");
    expect([...urlOf(fetchMock.mock.calls[0]).searchParams.keys()]).toEqual(["metric"]);
  });
});
