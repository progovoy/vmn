/** The noun pass (plan 19 U10): the create flow and Compare say "run", and the
 *  toolbar's create button hides where nothing can be created. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../api", () => ({
  api: {
    meta: vi.fn(),
    workspaces: vi.fn(),
    apps: vi.fn(),
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    experiment: vi.fn(),
    experimentsDiff: vi.fn(),
    recentExperiments: vi.fn(),
    action: vi.fn(),
    job: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
const appStatus = vi.hoisted(() => vi.fn());
vi.mock("../../apiShell", () => ({ apiShell: { appStatus: () => appStatus() } }));
const KNOWN_APP = {
  total: 1, counts: { created: 0, running: 0, stuck: 0, succeeded: 1, failed: 0 }, failed_recent: 0, rollup: null,
};
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/MetricBarChart", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 48, size: 48, end: (index + 1) * 48,
      })),
  }),
}));

import { api } from "../../api";
import { createQueryClient } from "../../queryClient";
import NewExperiment from "../../components/NewExperiment";
import Compare from "../Compare";
import { page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const GIT_WS = { name: "test", kind: "git", path: "/srv/test" };

beforeEach(() => {
  vi.clearAllMocks();
  m.meta.mockResolvedValue({ version: "0.10.2" });
  m.workspaces.mockResolvedValue([GIT_WS]);
  appStatus.mockResolvedValue(KNOWN_APP);
  m.apps.mockResolvedValue([{ name: "my/app", experiments: 1, versions: 1 }]);
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page([row(1)]));
  m.experimentsPaged.mockResolvedValue({ rows: [row(1)], total: 1 });
});

/** Waits until meta and the workspaces are in, so the toolbar has decided. */
async function boardSettled() {
  renderBoard();
  await screen.findByText("0.0.1-dev.x");
  await waitFor(() => expect(m.meta).toHaveBeenCalled());
  await waitFor(() => expect(m.workspaces).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 0));
}

describe("leaderboard toolbar create button", () => {
  it("reads New run in a writable git workspace", async () => {
    await boardSettled();
    expect(await screen.findByRole("button", { name: "New run" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /experiment/i })).toBeNull();
  });

  it("is hidden for an app the server does not know (spec §1.6)", async () => {
    appStatus.mockRejectedValue(
      Object.assign(new Error("x"), { status: 404, body: { detail: "x", code: "app_not_found" } }),
    );
    await boardSettled();
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByRole("button", { name: "New run" })).toBeNull();
  });

  it("is hidden on a read-only server", async () => {
    m.meta.mockResolvedValue({ version: "0.10.2", read_only: true });
    await boardSettled();
    await waitFor(() => expect(screen.queryByRole("button", { name: "New run" })).toBeNull());
  });

  it("is hidden in a store workspace", async () => {
    m.workspaces.mockResolvedValue([{ name: "test", kind: "store", store: "s3://team/ml" }]);
    await boardSettled();
    await waitFor(() => expect(screen.queryByRole("button", { name: "New run" })).toBeNull());
  });
});

describe("the new-run form", () => {
  it("is headed New run and creates a run", () => {
    render(
      <QueryClientProvider client={createQueryClient()}>
        <NewExperiment ws="test" app="my-app" appName="my_app" onCreated={() => {}} onClose={() => {}} />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("heading", { level: 2, name: "New run" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create run" })).toBeInTheDocument();
    expect(screen.getByText(/as a reproducible run\./)).toBeInTheDocument();
    expect(screen.queryByText(/experiment/i)).toBeNull();
  });
});

describe("Compare copy", () => {
  it("says two runs, for the sub line and identical code", async () => {
    m.experimentsDiff.mockResolvedValue({ from_verstr: "a", to_verstr: "b", metrics_delta: {}, diff: "" });
    m.recentExperiments.mockResolvedValue([]);
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={["/ws/w/app/app/compare?v=a&to=b"]}>
          <Routes><Route path="/ws/:ws/app/:app/compare" element={<Compare />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("The two runs have identical code.")).toBeInTheDocument();
    expect(screen.getByText(/source diff between two runs/)).toBeInTheDocument();
    expect(screen.queryByText(/two experiments/)).toBeNull();
  });
});
