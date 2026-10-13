import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchRunBaselines, fetchRunPatch } from "../apiRunCode";
import type { RunBaselines, RunPatch } from "../apiRunCode";
import type { ExperimentDetail } from "../types";

const urlOf = (call: unknown[]) => new URL(call[0] as string, "http://x");
const respond = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

describe("apiRunCode", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(() => respond({}));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("reads a run's patch under the app tag, the verstr encoded", async () => {
    const patch: RunPatch = {
      text: "=== working_tree ===\n", truncated: false,
      files: [{ path: "train.py", added: 1, removed: 1 }],
    };
    fetchMock.mockImplementation(() => respond(patch));
    expect(await fetchRunPatch("w", "root/svc", "0.0.1-dev.a+b")).toEqual(patch);
    const url = urlOf(fetchMock.mock.calls[0]);
    expect(url.pathname).toBe("/api/v1/workspaces/w/apps/root-svc/experiments/0.0.1-dev.a%2Bb/patch");
    expect(url.search).toBe("");
  });

  it("passes max_bytes when asked", async () => {
    await fetchRunPatch("w", "app", "v1", 4096);
    expect(urlOf(fetchMock.mock.calls[0]).searchParams.get("max_bytes")).toBe("4096");
  });

  it("types a run without text by its reason", async () => {
    const none: RunPatch = { text: null, reason: "no_code", files: [] };
    fetchMock.mockImplementation(() => respond(none));
    const got = await fetchRunPatch("w", "app", "v1");
    expect(got.text).toBeNull();
    expect(got.reason).toBe("no_code");
  });

  it("reads a run's baselines", async () => {
    const ref = { verstr: "v0", idx: 3, name: "good", status: "succeeded" };
    const body: RunBaselines = { previous: ref, best: { ...ref, verstr: "v9" } };
    fetchMock.mockImplementation(() => respond(body));
    expect(await fetchRunBaselines("w", "app", "v1")).toEqual(body);
    expect(urlOf(fetchMock.mock.calls[0]).pathname)
      .toBe("/api/v1/workspaces/w/apps/app/experiments/v1/baselines");
  });

  it("run detail types the failure context fields", () => {
    const detail: Pick<ExperimentDetail, "output_tail" | "last_step" | "last_good"> = {
      output_tail: { lines: ["boom"], truncated: false },
      last_step: { step: 38, of: 86 },
      last_good: { verstr: "v0", idx: 41, name: "hist-000488" },
    };
    expect(detail.last_step?.of).toBe(86);
  });
});
