/** Plan 23 W7: an inner run's page names its job, its place in the order
 *  the job's Runs tab showed, its rank on the job's metric, prev/next (also
 *  on [ and ]) and its value on the job's distribution. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", async (orig) => {
  const actual = await orig<typeof import("../../api")>();
  return { ...actual, api: { experimentsPaged: vi.fn(), metricsSchema: vi.fn() } };
});
vi.mock("../../apiJob", () => ({ jobSummary: vi.fn() }));

import { api } from "../../api";
import { jobSummary } from "../../apiJob";
import type { PageOpts } from "../../api";
import { jobSummaryFixture, JOB } from "../../pages/Job/__tests__/jobFixture";
import type { ExperimentRow } from "../../types";
import { runContextSearch } from "../../util/runContext";
import JobContextBar from "../JobContextBar";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const ME = "0.0.2-dev.t5";
const row = (i: number) => ({ idx: i, verstr: `0.0.2-dev.t${i}` } as ExperimentRow);
const ORDER = { scope: JOB, q: "metrics.val_loss < 1", sort: "val_loss", order: "asc" as const };

function Where() {
  const { pathname, search } = useLocation();
  return <output data-testid="where">{pathname + search}</output>;
}

function renderBar(search = "", metrics: Record<string, number> = { val_loss: 0.25 }) {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${ME}${search}`]}>
      <Routes>
        <Route path="/ws/:ws/app/:app/run/:verstr" element={(
          <><JobContextBar ws="test" app="my-app" verstr={ME} idx={5} job={JOB} metrics={metrics} /><Where /></>
        )} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({ val_loss: { goal: "min" } });
  vi.mocked(jobSummary).mockResolvedValue(jobSummaryFixture());
  m.experimentsPaged.mockImplementation((_w: string, _a: string, o: PageOpts) => {
    if (o.query?.includes("metrics.val_loss < 0.25")) return Promise.resolve({ rows: [], total: 2 });
    if (o.query === "idx > 5") return Promise.resolve({ rows: [], total: 7 });
    if (o.limit === 3) return Promise.resolve({ rows: [row(4), row(5), row(6)], total: 40 });
    return Promise.reject(new Error(`unexpected ${JSON.stringify(o)}`));
  });
});

describe("JobContextBar", () => {
  it("names the job, the run's place in the Runs tab's order and its neighbours", async () => {
    renderBar(runContextSearch(ORDER, 5));
    const bar = await screen.findByRole("navigation", { name: "Job context" });
    expect(await screen.findByRole("link", { name: "lr_layers_grid" })).toHaveAttribute("href", `/ws/test/app/my-app/run/${JOB}?tab=runs`);
    await waitFor(() => expect(bar).toHaveTextContent("run 6 of 40"));
    expect(m.experimentsPaged).toHaveBeenCalledWith("test", "my-app",
      expect.objectContaining({ scope: JOB, query: "metrics.val_loss < 1", sort: "val_loss", order: "asc", offset: 4, limit: 3 }));
    const prev = screen.getByRole("link", { name: /prev/ });
    const params = new URLSearchParams(prev.getAttribute("href")!.split("?")[1]);
    expect(prev.getAttribute("href")).toMatch(/\/run\/0\.0\.2-dev\.t4\?/);
    expect(params.get("at")).toBe("4");
    expect(new URLSearchParams(params.get("from")!).get("sort")).toBe("val_loss");
    expect(screen.getByRole("link", { name: /next/ }).getAttribute("href")).toMatch(/t6\?.*at=6/);
  });

  it("ranks the run on the job's metric within the job", async () => {
    renderBar(runContextSearch(ORDER, 5));
    const bar = await screen.findByRole("navigation", { name: "Job context" });
    await waitFor(() => expect(bar).toHaveTextContent("rank 3 of 1,409 on val_loss"));
    expect(m.experimentsPaged).toHaveBeenCalledWith("test", "my-app",
      expect.objectContaining({ scope: JOB, query: "metrics.val_loss < 0.25", limit: 1 }));
  });

  it("without an order, follows the job's default one (newest first)", async () => {
    renderBar();
    const bar = await screen.findByRole("navigation", { name: "Job context" });
    await waitFor(() => expect(bar).toHaveTextContent("run 8 of 40"));
    expect(m.experimentsPaged).toHaveBeenCalledWith("test", "my-app",
      expect.objectContaining({ scope: JOB, query: "idx > 5", sort: "idx", limit: 1 }));
    expect(m.experimentsPaged).toHaveBeenCalledWith("test", "my-app",
      expect.objectContaining({ scope: JOB, sort: "idx", offset: 6, limit: 3 }));
  });

  it("goes to the next and previous run on ] and [", async () => {
    renderBar(runContextSearch(ORDER, 5));
    await screen.findByRole("link", { name: /next/ });
    fireEvent.keyDown(document.body, { key: "]" });
    expect(screen.getByTestId("where").textContent).toMatch(/\/run\/0\.0\.2-dev\.t6\?/);
  });

  it("marks the run's value on the job's distribution", async () => {
    renderBar(runContextSearch(ORDER, 5));
    expect(await screen.findByRole("img", { name: "val_loss 0.25 among 1,409 runs of the job" })).toBeInTheDocument();
  });

  it("ranks nothing when the job's metrics have no goal", async () => {
    vi.mocked(jobSummary).mockResolvedValue(jobSummaryFixture({ ranked: false }));
    renderBar(runContextSearch(ORDER, 5));
    const bar = await screen.findByRole("navigation", { name: "Job context" });
    await waitFor(() => expect(bar).toHaveTextContent("run 6 of 40"));
    expect(bar).not.toHaveTextContent("rank");
  });
});
