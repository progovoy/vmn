/** Plan 23 W11 (§3.5): a job's Runs tab searches within the job, with a
 *  `search all runs` link that drops the scope (All runs, same filter). */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../../../api", async (orig) => {
  const actual = await orig<typeof import("../../../api")>();
  return {
    ...actual,
    api: {
      experiment: vi.fn(), experiments: vi.fn(), experimentsPaged: vi.fn(), experimentGroups: vi.fn(),
      experimentGroupRows: vi.fn(), experimentsColumns: vi.fn(), facets: vi.fn(), metricsSchema: vi.fn(),
      action: vi.fn(), actionPreview: vi.fn(), job: vi.fn(),
    },
  };
});
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * 48, size: 48, end: (index + 1) * 48 })),
  }),
}));

import { api } from "../../../api";
import JobRuns from "../JobRuns";

const JOB = "0.0.2-rc.1";
const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function renderRuns(search: string) {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${JOB}${search}`]}>
      <Routes>
        <Route path="/ws/:ws/app/:app/run/:verstr"
          element={<JobRuns ws="test" app="my-app" verstr={JOB} paused={false} onPaused={() => {}} />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 0 });
  m.facets.mockResolvedValue({ branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {}, total: 0 });
  m.experimentsColumns.mockResolvedValue({ verstrs: [], idx: [], columns: {}, total: 0 });
});

describe("search all runs", () => {
  it("links a search in the job to All runs with the same filter", async () => {
    renderRuns("?tab=runs&search=grid&q=metrics.loss%20%3C%200.2");
    const link = await screen.findByRole("link", { name: "search all runs" });
    const href = new URL(link.getAttribute("href")!, "http://x");
    expect(href.pathname).toBe("/ws/test/app/my-app");
    expect([href.searchParams.get("view"), href.searchParams.get("search"), href.searchParams.get("q")])
      .toEqual(["all", "grid", "metrics.loss < 0.2"]);
    expect(href.searchParams.get("scope")).toBeNull();
  });

  it("is not shown without a search", async () => {
    renderRuns("?tab=runs");
    await screen.findByText(/0 runs/);
    expect(screen.queryByRole("link", { name: "search all runs" })).toBeNull();
  });
});
