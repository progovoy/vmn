/** Plan 28 N6 follow-up: a tree page carries the Runs tab's filters; its
 *  status and query match subtrees (`match_subtree=1`). */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchChildren } from "../apiTree";

const urlOf = (call: unknown[]) => new URL(call[0] as string, "http://x");

describe("a tree page's filters", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => Promise.resolve(new Response('{"rows":[],"total":0}', { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("asks for the filters it is given, matching subtrees", async () => {
    await fetchChildren("w", "app", "v1", {
      offset: 100, filter: { status: "failed", query: 'tags.kind = "date"', sort: "loss", order: "asc", archived: true },
    });
    const p = urlOf(fetchMock.mock.calls[0]).searchParams;
    expect(p.get("children_of")).toBe("v1");
    expect(p.get("offset")).toBe("100");
    expect(p.get("status")).toBe("failed");
    expect(p.get("q")).toBe('tags.kind = "date"');
    expect(p.get("sort")).toBe("loss");
    expect(p.get("order")).toBe("asc");
    expect(p.get("archived")).toBe("1");
    expect(p.get("match_subtree")).toBe("1");
  });

  it("sorts without matching subtrees when nothing filters", async () => {
    await fetchChildren("w", "app", "v1", { filter: { sort: "job:attention" } });
    const p = urlOf(fetchMock.mock.calls[0]).searchParams;
    expect(p.get("sort")).toBe("job:attention");
    for (const k of ["status", "q", "order", "archived", "match_subtree"]) expect(p.has(k)).toBe(false);
  });
});
