/** Plan 28 P3: a job's summary split by a tag or param (`?split=`). */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { jobSummary } from "../apiJob";
import { jobSummaryKey, jobSummaryQuery } from "../pages/Job/jobQueries";

const urlOf = (call: unknown[]) => new URL(call[0] as string, "http://x");

describe("job summary split", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => Promise.resolve(new Response("{}", { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("asks for the split it is given", async () => {
    await jobSummary("w", "app", "v1", "tags.kind");
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.pathname).toBe("/api/v1/workspaces/w/apps/app/experiments/v1/summary");
    expect(url.searchParams.get("split")).toBe("tags.kind");
  });

  it("leaves the server's default without one", async () => {
    await jobSummary("w", "app", "v1");
    expect(urlOf(fetchMock.mock.calls[0]).searchParams.has("split")).toBe(false);
  });

  it("keys a split summary under the summary key, so a refresh reaches it", () => {
    const key = jobSummaryQuery("w", "app", "v1", "tags.kind").queryKey;
    expect(key.slice(0, jobSummaryKey("w", "app", "v1").length)).toEqual(jobSummaryKey("w", "app", "v1"));
    expect(key).not.toEqual(jobSummaryQuery("w", "app", "v1").queryKey);
  });
});
