/** The job's progress (plan 23 W1): its run bar and its progress line. */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import JobProgress from "../JobProgress";
import { NO_COUNTS, job } from "../../util/__tests__/jobFixture";

describe("JobProgress", () => {
  it("shows the bar and the line, one sentence for a screen reader", () => {
    const { container } = render(<JobProgress job={job()} />);
    expect(container.querySelectorAll(".job-bar-seg")).toHaveLength(3);
    expect(container.querySelector(".job-progress-text")?.textContent).toBe("1,412/2,000 · 3 failed · 41/min · ETA 14m");
    expect(screen.getByText(/1,412 of 2,000 runs done/)).toHaveClass("sr-only");
  });

  it("reads a finished job's count alone", () => {
    render(<JobProgress job={job({
      done: 5, expected: 5, total: 5, eta_sec: 0, throughput_per_min: 0, counts: { ...NO_COUNTS, succeeded: 5 },
    })} />);
    expect(screen.getByText("5/5")).toBeInTheDocument();
  });
});
