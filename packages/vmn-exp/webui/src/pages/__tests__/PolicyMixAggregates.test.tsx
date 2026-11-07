/** Plan 32 F1 follow-up: a pivot cell, a job's best (Jobs view, tree, KPI
 *  tile) and a baseline delta aggregating runs that override the schema's
 *  summary policy say so: a `*` marker whose title reads `2 runs use min`. */
import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { Pivot, PivotCell } from "../../apiPivot";
import PivotHeatmap from "../../components/PivotHeatmap";
import { cellLabel } from "../../util/pivotCells";
import type { ExperimentRow, JobRollup } from "../../types";
import { BestValue } from "../Experiments/JobCells";
import { jobKpis } from "../Job/jobData";
import { jobSummaryFixture } from "../Job/__tests__/jobFixture";
import { compareFixture } from "../../components/__tests__/baselineFixture";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiBaseline", () => ({ jobBaseline: vi.fn() }));
import { jobBaseline } from "../../apiBaseline";
import JobBaseline from "../Job/JobBaseline";

const MIXED: PivotCell = { n: 3, value: 0.5, clause: "a = 1", mixed: true, policies: { min: 1 } };
const PLAIN: PivotCell = { n: 2, value: 0.4, clause: "a = 2" };

const PIVOT: Pivot = {
  rows: [{ key: "d1", label: "d1", n: 5, clause: 'tags.date = "d1"' }],
  cols: [{ key: "g1", label: "g1", n: 3, clause: 'tags.group = "g1"' },
    { key: "g2", label: "g2", n: 2, clause: 'tags.group = "g2"' }],
  cells: [[MIXED, PLAIN]],
  total: 5, rows_total: 1, cols_total: 2, cell: "agg", match: null, metric: "loss", agg: "median", goal: "min",
};

describe("a pivot cell over overrides", () => {
  it("names them in its label", () => {
    expect(cellLabel(PIVOT, "tags.date", "tags.group", 0, 0, MIXED))
      .toBe("tags.date d1, tags.group g1: median loss 0.5 (3 runs) · 1 run uses min");
    expect(cellLabel(PIVOT, "tags.date", "tags.group", 0, 1, PLAIN))
      .toBe("tags.date d1, tags.group g2: median loss 0.4 (2 runs)");
  });

  it("carries a marker, a plain cell none", () => {
    render(
      <MemoryRouter>
        <PivotHeatmap pivot={PIVOT} rowsField="tags.date" colsField="tags.group" hrefOf={(q) => q} />
      </MemoryRouter>,
    );
    const [mixed, plain] = screen.getAllByRole("cell");
    expect(within(mixed).getByTitle("1 run uses min")).toHaveTextContent("*");
    expect(plain.querySelector(".policy-mix-mark")).toBeNull();
  });
});

const jobRow = (over: Partial<JobRollup> = {}) => ({
  idx: 1, verstr: "job", code_verstr: "job", timestamp: null, note: null, branch: null, base_version: null,
  metrics: {},
  job: { metric: "loss", goal: "min", best: 0.2, best_verstr: "v7", best_idx: 7, spread: [], ...over },
}) as unknown as ExperimentRow;

const CTX = { runBase: "/ws/w/app/a", metric: "loss", goal: "min" as const };

describe("a job's best over overrides", () => {
  it("carries a marker and says so in its title", () => {
    render(<MemoryRouter><BestValue r={jobRow({ mixed: true, policies: { min: 2 } })} ctx={CTX} /></MemoryRouter>);
    expect(screen.getByTitle("best loss · 2 runs use min")).toBeInTheDocument();
    expect(screen.getByTitle("2 runs use min")).toHaveTextContent("*");
  });

  it("says nothing more without one", () => {
    render(<MemoryRouter><BestValue r={jobRow()} ctx={CTX} /></MemoryRouter>);
    expect(screen.getByTitle("best loss")).toBeInTheDocument();
    expect(document.querySelector(".policy-mix-mark")).toBeNull();
  });

  it("names them under the KPI tile", () => {
    const s = jobSummaryFixture();
    s.metrics.val_loss = { ...s.metrics.val_loss!, mixed: true, policies: { last: 3 } };
    expect(jobKpis(s).find((t) => t.label === "best val_loss")?.sub).toBe("3 runs use last");
    expect(jobKpis(jobSummaryFixture()).find((t) => t.label === "best val_loss")?.sub).toBeUndefined();
  });
});

describe("a baseline delta over overrides", () => {
  it("marks the metric's rows, naming each side's", async () => {
    const data = compareFixture();
    data.metrics.best_value = { ...data.metrics.best_value, policies: { value: { min: 2 }, baseline: null } };
    vi.mocked(jobBaseline).mockResolvedValue(data);
    renderWithClient(<MemoryRouter><JobBaseline ws="test" app="my-app" verstr="0.0.2-rc.1" done={1} /></MemoryRouter>);
    const table = await screen.findByRole("table", { name: "Against the baseline" });
    const best = within(table).getByRole("row", { name: /best best_value/ });
    expect(within(best).getByTitle("this: 2 runs use min")).toHaveTextContent("*");
    expect(within(table).getByRole("row", { name: /median best_value/ }).querySelector(".policy-mix-mark")).not.toBeNull();
    expect(within(table).getByRole("row", { name: /failed/ }).querySelector(".policy-mix-mark")).toBeNull();
  });
});
