/** Plan 28 P2: an outer run's page reads its declared progress — the
 *  header's bar and line, the done tile — the runs done a tile of their own. */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import JobHeaderProgress from "../JobHeaderProgress";
import { jobKpis } from "../jobData";
import { jobSummaryFixture } from "./jobFixture";

const declared = () => jobSummaryFixture({
  progress: 0.6833, declared_progress: { done: 41, total: 60, unit: "dates", rate_per_min: 2 },
});

describe("an outer run's page with a declared progress", () => {
  it("measures the header bar in its unit and leads the line with it", () => {
    render(<JobHeaderProgress summary={declared()} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuemax", "60");
    expect(bar).toHaveAttribute("aria-valuenow", "41");
    expect(bar.getAttribute("aria-label")).toMatch(/^41 of 60 dates done, 2,000 runs/);
    expect(screen.getByText("41/60 dates")).toBeInTheDocument();
  });

  it("shows it on the done tile and the runs done on their own", () => {
    const byLabel = Object.fromEntries(jobKpis(declared()).map((t) => [t.label, t]));
    expect([byLabel["done"].value, byLabel["done"].sub]).toEqual(["41", "of 60 dates"]);
    expect([byLabel["runs done"].value, byLabel["runs done"].sub]).toEqual(["1,412", "of 2,000"]);
  });

  it("keeps the done tile in runs without one", () => {
    const labels = jobKpis(jobSummaryFixture()).map((t) => t.label);
    expect(labels).not.toContain("runs done");
  });
});
