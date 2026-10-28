/** Plan 28 N2: the outer run's Overview pivots its runs by two fields picked
 *  from its facets; each cell opens the Runs tab filtered to it. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../../../apiPivot", () => ({ pivot: vi.fn() }));
vi.mock("../../../apiJobCharts", () => ({ jobFacets: vi.fn() }));

import { pivot, type Pivot } from "../../../apiPivot";
import { jobFacets } from "../../../apiJobCharts";
import JobPivot from "../JobPivot";
import { JOB } from "./jobFixture";

const PIVOT: Pivot = {
  rows: [{ key: "d1", label: "d1", n: 2, clause: 'tags.date = "d1"' }],
  cols: [{ key: "g1", label: "g1", n: 2, clause: 'tags.group = "g1"' }],
  cells: [[{ n: 2, value: 2, clause: 'tags.date = "d1" and tags.group = "g1"' }]],
  total: 2, rows_total: 1, cols_total: 1, cell: "count", match: null, metric: null, agg: null,
};

function renderPivot() {
  return renderWithClient(
    <MemoryRouter><JobPivot ws="test" app="my-app" verstr={JOB} metrics={["val_loss", "acc"]} done={10} /></MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(jobFacets).mockResolvedValue({
    branches: [], metric_keys: ["val_loss"], param_keys: ["lr"], tag_keys: ["date", "group"],
    param_values: {}, parented: 0, total: 2, jobs: 0, singles: 0,
  });
  vi.mocked(pivot).mockResolvedValue(PIVOT);
});

describe("job pivot", () => {
  it("pivots the outer run's runs by its first two tags", async () => {
    renderPivot();
    await waitFor(() => expect(pivot).toHaveBeenCalledWith("test", "my-app",
      { scope: JOB, rows: "tags.date", cols: "tags.group", cell: "count" }));
    const cell = await screen.findByRole("link", { name: /tags.date d1, tags.group g1: 2 runs/ });
    expect(cell).toHaveAttribute("href",
      `/ws/test/app/my-app/run/${JOB}?${new URLSearchParams({ tab: "runs", q: 'tags.date = "d1" and tags.group = "g1"' })}`);
  });

  it("asks for a share of the runs matching a query", async () => {
    renderPivot();
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText("Cell"), { target: { value: "share" } });
    const match = screen.getByLabelText("Matching");
    fireEvent.change(match, { target: { value: 'tags.health = "unstable"' } });
    fireEvent.submit(match.closest("form")!);
    await waitFor(() => expect(pivot).toHaveBeenLastCalledWith("test", "my-app",
      { scope: JOB, rows: "tags.date", cols: "tags.group", cell: "share", match: 'tags.health = "unstable"' }));
  });

  it("asks for an aggregate of a metric", async () => {
    renderPivot();
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText("Cell"), { target: { value: "agg" } });
    fireEvent.change(screen.getByLabelText("Aggregate"), { target: { value: "min" } });
    await waitFor(() => expect(pivot).toHaveBeenLastCalledWith("test", "my-app",
      { scope: JOB, rows: "tags.date", cols: "tags.group", cell: "agg", metric: "val_loss", agg: "min" }));
  });

  it("swaps the axes from the pickers", async () => {
    renderPivot();
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText("Rows"), { target: { value: "params.lr" } });
    await waitFor(() => expect(pivot).toHaveBeenLastCalledWith("test", "my-app",
      { scope: JOB, rows: "params.lr", cols: "tags.group", cell: "count" }));
  });

  it("shows the server's error", async () => {
    vi.mocked(pivot).mockRejectedValue(new Error("bad match query"));
    renderPivot();
    expect(await screen.findByRole("alert")).toHaveTextContent("bad match query");
  });
});
