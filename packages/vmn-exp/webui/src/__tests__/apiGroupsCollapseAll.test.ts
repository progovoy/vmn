import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchGroups } from "../apiGroups";

const urlOf = (call: unknown[]) => new URL(call[0] as string, "http://x");
const respond = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));

describe("one row per group (plan 34 §1)", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => respond({ groups: [], total_groups: 0, total_rows: 0 }));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("asks for the headers alone with collapse_all=1", async () => {
    await fetchGroups("w", "app", { group: "tags.launch_id", top: "jobs", collapseAll: true });
    expect(urlOf(fetchMock.mock.calls[0]).searchParams.get("collapse_all")).toBe("1");
  });

  it("leaves it out otherwise", async () => {
    await fetchGroups("w", "app", { group: "tags.launch_id", top: "jobs" });
    expect(urlOf(fetchMock.mock.calls[0]).searchParams.has("collapse_all")).toBe(false);
  });
});
