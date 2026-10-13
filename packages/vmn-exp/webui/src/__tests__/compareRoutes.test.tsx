import { describe, it, expect, vi, beforeEach, beforeAll, afterAll } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

vi.mock("uplot", async () => await import("../components/__tests__/fakeUPlot"));
vi.mock("../api", () => ({
  api: {
    workspaces: vi.fn(), meta: vi.fn(), apps: vi.fn(),
    experimentsDiff: vi.fn(), metricsSchema: vi.fn(), recentExperiments: vi.fn(),
    experimentsPaged: vi.fn(), experiment: vi.fn(),
  },
  appName: (t: string) => t.replaceAll("-", "/"),
  appTag: (n: string) => n.replaceAll("/", "-"),
}));
vi.mock("../apiSeries", () => ({ fetchSeriesBatch: vi.fn(), fetchRunStatuses: vi.fn() }));

import { api } from "../api";
import { fetchRunStatuses, fetchSeriesBatch } from "../apiSeries";
import { createQueryClient } from "../queryClient";
import { routes } from "../routes";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

// A data router builds a fetch Request per navigation; Node's Request rejects
// jsdom's AbortSignal, so drop the signal in this environment only.
const NodeRequest = globalThis.Request;
beforeAll(() => {
  globalThis.Request = class extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(input, init && { ...init, signal: undefined });
    }
  } as typeof Request;
});
afterAll(() => { globalThis.Request = NodeRequest; });

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}
const where = (router: ReturnType<typeof renderAt>) =>
  router.state.location.pathname + router.state.location.search;

beforeEach(() => {
  vi.clearAllMocks();
  m.workspaces.mockResolvedValue([{ name: "w", kind: "local", path: "/tmp/w" }]);
  m.meta.mockResolvedValue({ version: "1.2.3" });
  m.apps.mockResolvedValue([]);
  m.metricsSchema.mockResolvedValue({});
  m.recentExperiments.mockResolvedValue([]);
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 0 });
  m.experimentsDiff.mockResolvedValue({ from_verstr: "a", to_verstr: "b", metrics_delta: {}, diff: "" });
  (fetchSeriesBatch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ series: {}, missing: [] });
  (fetchRunStatuses as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({});
});

describe("Compare routes", () => {
  it("redirects an old overlay link to the curves tab, crumb `compare N runs`", async () => {
    const router = renderAt("/ws/w/app/a/overlay?runs=a,b");
    await waitFor(() => expect(where(router)).toBe("/ws/w/app/a/compare-runs?tab=curves&sel=a&sel=b"));
    expect(await screen.findByRole("tab", { name: "Curves" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("compare 2 runs")).toBeInTheDocument();
  });

  it("redirects an old code diff link to the code tab", async () => {
    const router = renderAt("/ws/w/app/a/compare?v=a&to=b");
    await waitFor(() => expect(where(router)).toBe("/ws/w/app/a/compare-runs?tab=code&sel=a&sel=b"));
    expect(await screen.findByRole("tab", { name: "Code" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(m.experimentsDiff).toHaveBeenCalledWith("w", "a", "a", "b"));
  });

  it("replaces the old entry, so Back skips the redirect", async () => {
    const router = renderAt("/ws/w/app/a/overlay?runs=a,b");
    await waitFor(() => expect(router.state.location.pathname).toBe("/ws/w/app/a/compare-runs"));
    expect(router.state.historyAction).toBe("REPLACE");
  });
});
