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
});
