/** One status colour map: the job charts and the run page's Fleet card. */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { STATUS_COLORS, statusLabel } from "../statusColors";
import { STATUS_COLORS as JOB_CHART_COLORS } from "../../pages/Job/jobChartData";
import { FleetCard } from "../../pages/RunSections";

describe("STATUS_COLORS", () => {
  it("wears the --st-* status tokens, waiting like created", () => {
    expect(STATUS_COLORS).toEqual({
      running: "var(--st-running)", stuck: "var(--st-stuck)", failed: "var(--st-bad)",
      succeeded: "var(--st-good)", created: "var(--text-3)", waiting: "var(--text-3)",
    });
    expect(JOB_CHART_COLORS).toBe(STATUS_COLORS);
  });

  it("calls created runs waiting", () => {
    expect(statusLabel("created")).toBe("waiting");
    expect(statusLabel("failed")).toBe("failed");
  });

  it("colours the Fleet card's dots and bar the same", () => {
    const fleet = { counts: { failed: 1, succeeded: 3 }, expected: 4, children: [] };
    const { container } = render(<FleetCard fleet={fleet as never} runUrl={(v) => v} table={false} />);
    const segs = [...container.querySelectorAll<HTMLElement>(".fleet-bar .segment")].map((s) => s.style.background);
    expect(segs).toEqual(["var(--st-good)", "var(--st-bad)"]);
  });
});
