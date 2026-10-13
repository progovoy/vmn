import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { jobFailures, jobImportance, jobSummary } from "../apiJob";

const urlOf = (call: unknown[]) => new URL(call[0] as string, "http://x");
const respond = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

describe("apiJob (plan 23 §10)", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => respond({}));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("reads a job's summary under the app tag, the verstr encoded", async () => {
    fetchMock.mockImplementation(() => respond({ total: 3 }));
    expect(await jobSummary("w", "root/svc", "0.0.1-dev.a+b")).toEqual({ total: 3 });
    expect(urlOf(fetchMock.mock.calls[0]).pathname)
      .toBe("/api/v1/workspaces/w/apps/root-svc/experiments/0.0.1-dev.a%2Bb/summary");
  });

  it("reads a job's failure clusters with a limit", async () => {
    await jobFailures("w", "app", "v1");
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.pathname).toBe("/api/v1/workspaces/w/apps/app/experiments/v1/failures");
    expect(url.searchParams.get("limit")).toBe("20");
  });

  it("scopes param importance to the job's subtree", async () => {
    fetchMock.mockImplementation(() => respond([]));
    await jobImportance("w", "app", "v1", "loss");
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.pathname).toBe("/api/v1/workspaces/w/apps/app/experiments-importance");
    expect(url.searchParams.get("metric")).toBe("loss");
    expect(url.searchParams.get("scope")).toBe("v1");
  });

  it("throws the HTTP status, so a 404 can fall back to the single-run page", async () => {
    fetchMock.mockImplementation(() => respond({ detail: "no children" }, 404));
    await expect(jobSummary("w", "app", "v1")).rejects.toMatchObject({ status: 404 });
  });
});
