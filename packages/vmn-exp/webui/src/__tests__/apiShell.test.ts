import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiShell } from "../apiShell";

const urlOf = (call: unknown[]) => new URL(call[0] as string, "http://x");
const respond = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

describe("apiShell", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => respond({}));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("reads a workspace's git context", async () => {
    const git = { branch: "main", detached: false, head: "a".repeat(40), head_short: "aaaaaaa",
      dirty: false, store: ".vmn/store" };
    fetchMock.mockImplementation(() => respond(git));
    expect(await apiShell.gitContext("ml-repo")).toEqual(git);
    expect(urlOf(fetchMock.mock.calls[0]).pathname).toBe("/api/v1/workspaces/ml-repo/git");
  });

  it("reads an app's status under its tag", async () => {
    await apiShell.appStatus("w", "root-svc");
    expect(urlOf(fetchMock.mock.calls[0]).pathname)
      .toBe("/api/v1/workspaces/w/apps/root-svc/experiments-status");
  });

  it("resolves a ref through run detail with series off", async () => {
    fetchMock.mockImplementation(() =>
      respond({ metadata: { verstr: "0.1.0-dev.abc" }, idx: 54, name: "lr-sweep-3" }));
    expect(await apiShell.resolveRef("w", "my-app", "@54"))
      .toEqual({ verstr: "0.1.0-dev.abc", idx: 54, name: "lr-sweep-3" });
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.pathname).toBe("/api/v1/workspaces/w/apps/my-app/experiments/%4054");
    expect(url.searchParams.get("series")).toBe("false");
    expect(url.searchParams.get("max_points")).toBe("2");
  });

  it("fills idx and name with null when an older server omits them", async () => {
    fetchMock.mockImplementation(() => respond({ metadata: { verstr: "v" } }));
    expect(await apiShell.resolveRef("w", "a", "latest"))
      .toEqual({ verstr: "v", idx: null, name: null });
  });

  it("resolves an unknown ref to null", async () => {
    fetchMock.mockImplementation(() => respond({ detail: "Experiment @540 not found" }, 404));
    expect(await apiShell.resolveRef("w", "a", "@540")).toBeNull();
  });

  it("rethrows any other failure", async () => {
    fetchMock.mockImplementation(() => respond({ detail: "boom" }, 500));
    await expect(apiShell.resolveRef("w", "a", "@1")).rejects.toMatchObject({ status: 500 });
  });
});
