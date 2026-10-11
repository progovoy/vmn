import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { runSimilar, textSimilar } from "../apiSimilar";

const urlOf = (call: unknown[]) => new URL(call[0] as string, "http://x");
const EMPTY = { items: [], truncated: false };

describe("apiSimilar filters", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify(EMPTY), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("sends a candidate query as q and archived as 1", async () => {
    await textSimilar("w", "app", "focal", { query: 'status = "failed"', archived: true });
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.searchParams.get("q")).toBe('status = "failed"');
    expect(url.searchParams.get("archived")).toBe("1");
  });

  it("leaves both out when unset or empty", async () => {
    await textSimilar("w", "app", "focal", { query: "", archived: false });
    await runSimilar("w", "app", "v");
    for (const call of fetchMock.mock.calls) {
      const url = urlOf(call);
      expect(url.searchParams.has("q")).toBe(false);
      expect(url.searchParams.has("archived")).toBe(false);
    }
  });
});
