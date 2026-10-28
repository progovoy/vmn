/** Plan 28 N3: the outer run's Overview compares it with its baseline — the
 *  run it was matched with, the chip, the rollup deltas and its children
 *  paired by key, the worse ones marked. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../../../apiBaseline", () => ({ jobBaseline: vi.fn() }));

import { jobBaseline } from "../../../apiBaseline";
import { compareFixture } from "../../../components/__tests__/baselineFixture";
import JobBaseline, { JobBaselineChip } from "../JobBaseline";
import JobHeader from "../JobHeader";
import { JOB, jobSummaryFixture } from "./jobFixture";

function renderCard() {
  return renderWithClient(<MemoryRouter><JobBaseline ws="test" app="my-app" verstr={JOB} done={10} /></MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(jobBaseline).mockResolvedValue(compareFixture());
});

describe("the baseline card", () => {
  it("names the baseline and how it was picked", async () => {
    renderCard();
    const link = await screen.findByRole("link", { name: "@12 wf_41aa" });
    expect(link).toHaveAttribute("href", "/ws/test/app/my-app/run/0.0.1-dev.base");
    expect(screen.getByText(/latest ended outer run with the same params.table_name, params.model_type/)).toBeInTheDocument();
    expect(screen.getByText(/▼ best_value from 2024-12/)).toHaveClass("baseline-worse");
    expect(jobBaseline).toHaveBeenCalledWith("test", "my-app", JOB);
  });

  it("lists the rollup deltas, an improvement told from a regression", async () => {
    renderCard();
    const table = await screen.findByRole("table", { name: "Against the baseline" });
    const row = (name: string) => within(table).getByRole("row", { name: new RegExp(name) });
    expect(row("best best_value")).toHaveTextContent("1.21");
    expect(within(row("best best_value")).getByText("-0.09")).toHaveClass("delta-worse");
    expect(within(row("median best_value")).getByText("+0.1")).toHaveClass("delta-better");
    expect(row("failed")).toHaveTextContent("5%");
    expect(row("p90 duration")).toHaveTextContent("2h");
    expect(row("unstable")).toHaveTextContent("12%");
    expect(row("cost_per_date")).toHaveTextContent("+1");
  });

  it("pairs the children by key, the worse ones marked", async () => {
    renderCard();
    const table = await screen.findByRole("table", { name: "Per trade_date" });
    const rows = within(table).getAllByRole("row").slice(1) as HTMLTableRowElement[];
    expect(rows.map((r) => r.cells[0].textContent)).toEqual(["2024-06", "2024-12", "2025-06"]);
    expect(rows[1]).toHaveClass("pair-worse");
    expect(rows[2]).toHaveTextContent("not finished");
    expect(screen.getByText("3 of 4 trade_date values matched")).toBeInTheDocument();
  });

  it("says when no outer run alike has ended yet", async () => {
    vi.mocked(jobBaseline).mockResolvedValue(compareFixture({ baseline: null, chip: null, pairs: [], metrics: {} }));
    renderCard();
    expect(await screen.findByText(
      "No ended outer run with the same params.table_name, params.model_type yet (tag one baseline=true to pin it).",
    )).toBeInTheDocument();
  });

  it("shows the server's error", async () => {
    vi.mocked(jobBaseline).mockRejectedValue(new Error("bad by"));
    renderCard();
    expect(await screen.findByRole("alert")).toHaveTextContent("bad by");
  });
});

describe("the header's baseline chip", () => {
  it("links the chip to the baseline run", async () => {
    renderWithClient(<MemoryRouter><JobBaselineChip ws="test" app="my-app" verstr={JOB} done={10} /></MemoryRouter>);
    const chip = await screen.findByRole("link", { name: /▼ best_value from 2024-12/ });
    expect(chip).toHaveAttribute("href", "/ws/test/app/my-app/run/0.0.1-dev.base");
  });

  it("is nothing without a baseline", async () => {
    vi.mocked(jobBaseline).mockResolvedValue(compareFixture({ baseline: null, chip: null }));
    const { container } = renderWithClient(<MemoryRouter><JobBaselineChip ws="test" app="my-app" verstr={JOB} done={10} /></MemoryRouter>);
    await waitFor(() => expect(jobBaseline).toHaveBeenCalled());
    expect(container.querySelector(".baseline-chip")).toBeNull();
  });

  it("sits in the header's title row", () => {
    render(<JobHeader summary={jobSummaryFixture()} actions={null} baseline={<span>chip here</span>} />);
    expect(screen.getByText("chip here").closest(".job-title")).not.toBeNull();
  });
});
