/** Plan 32 F13: the board's duration column shows a stuck run's lower bound
 *  marked (`≥ 3h (stuck)`), a running run's elapsed time marked `(running)`,
 *  and the run page's Status section the same. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));
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
import type { RunStatus } from "../../types";
import { StatusFacts } from "../RunSections";
import { summaryFromRow } from "../runSummary";
import { page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const cells = () => [...document.querySelectorAll('tbody td[data-col-id="c:duration"]')] as HTMLElement[];

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
});

describe("duration lower bound", () => {
  it("marks the board's stuck and running durations", async () => {
    m.experiments.mockResolvedValue(page([
      row(1, { status: "stuck", duration_sec: null, duration_at_least_sec: 11000 }),
      row(2, { status: "running", duration_sec: 600, duration_at_least_sec: null }),
    ]));
    renderBoard("/ws/test/app/my-app?show=c:duration");
    await screen.findByText("0.0.1-dev.x");
    expect(cells().map((c) => c.textContent)).toEqual(["≥ 3h (stuck)", "10m (running)"]);
    expect(cells()[0].title).toBe("at least 11000 s: stuck, it recorded no end");
  });

  it("keeps the lower bound in the run page's first paint from the board row", () => {
    const summary = summaryFromRow(row(1, { status: "stuck", duration_sec: null, duration_at_least_sec: 11000 }));
    expect(summary.status?.duration_at_least_sec).toBe(11000);
  });

  it("shows the lower bound in the run page's Status section", () => {
    const st = {
      status: "stuck", exit_code: null, started_at: null, finished_at: null, heartbeat: null,
      duration_sec: null, duration_at_least_sec: 11000, pid: null, host: null, command: null,
      stale_sec: 600,
    } as RunStatus;
    render(<StatusFacts st={st} runUrl={(v) => v} />);
    expect(screen.getByText("≥ 3h (stuck)")).toBeTruthy();
  });
});
