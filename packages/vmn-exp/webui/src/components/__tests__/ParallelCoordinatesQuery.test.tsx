/** The brush as a filter (plan 23 W4): ParallelCoordinates reports the
 *  query clause matching its brushed runs, and null once cleared. */
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ParallelCoordinates from "../ParallelCoordinates";
import type { ExperimentRow } from "../../types";

const row = (i: number, loss: number, lr: number): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null, branch: null,
  base_version: null, params: { lr }, metrics: { loss },
});
const ROWS = [row(1, 0.5, 0.01), row(2, 0.3, 0.001), row(3, 0.7, 0.1)];

describe("ParallelCoordinates brush query", () => {
  it("reports the brushed runs as a clause, then null on clear", () => {
    const onBrushQuery = vi.fn();
    const { container } = render(
      <ParallelCoordinates rows={ROWS} metricCols={["loss"]} paramCols={["lr"]} schema={null}
        onBrushQuery={onBrushQuery} />,
    );
    const area = container.querySelectorAll("[data-testid='brush-area']")[0];
    // The loss axis' upper half: 0.5 and 0.7.
    fireEvent.mouseDown(area, { clientY: 20 });
    fireEvent.mouseMove(area, { clientY: 150 });
    fireEvent.mouseUp(area, { clientY: 150 });
    expect(onBrushQuery).toHaveBeenLastCalledWith("metrics.loss >= 0.5 and metrics.loss <= 0.7");
    fireEvent.click(screen.getByRole("button", { name: "clear" }));
    expect(onBrushQuery).toHaveBeenLastCalledWith(null);
  });
});
