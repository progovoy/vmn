import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import ParallelCoordinates from "../ParallelCoordinates";
import type { ExperimentRow, MetricsSchema } from "../../types";

function makeRow(
  idx: number,
  metrics: Record<string, number | string>,
  user_meta: Record<string, unknown> | null = null,
): ExperimentRow {
  return {
    idx,
    verstr: `1.0.0-dev.${String.fromCharCode(96 + idx)}`,
    code_verstr: `1.0.0-dev.${String.fromCharCode(96 + idx)}`,
    timestamp: null,
    note: null,
    branch: "main",
    base_version: "1.0.0",
    user_meta,
    metrics,
  };
}

const ROWS: ExperimentRow[] = [
  makeRow(1, { loss: 0.5, acc: 0.8 }, { lr: 0.01 }),
  makeRow(2, { loss: 0.3, acc: 0.9 }, { lr: 0.001 }),
  makeRow(3, { loss: 0.7, acc: 0.7 }, { lr: 0.1 }),
];

const SCHEMA: MetricsSchema = {
  loss: { goal: "min" },
  acc: { goal: "max", primary: true },
};

describe("ParallelCoordinates", () => {
  it("renders correct number of axes from selected dimensions", () => {
    const { container } = render(
      <ParallelCoordinates
        rows={ROWS}
        metricCols={["loss", "acc"]}
        paramCols={["lr"]}
        schema={SCHEMA}
      />,
    );
    // Each dimension gets a vertical axis line with data-testid="axis"
    const axes = container.querySelectorAll("[data-testid='axis']");
    expect(axes).toHaveLength(3); // loss, acc, lr
  });

  it("renders correct number of polylines (one per row)", () => {
    const { container } = render(
      <ParallelCoordinates
        rows={ROWS}
        metricCols={["loss", "acc"]}
        paramCols={["lr"]}
        schema={SCHEMA}
      />,
    );
    const lines = container.querySelectorAll("[data-testid='row-line']");
    expect(lines).toHaveLength(3);
  });

  it("brush on an axis filters and emits correct indices", () => {
    const onBrush = vi.fn();
    const { container } = render(
      <ParallelCoordinates
        rows={ROWS}
        metricCols={["loss", "acc"]}
        paramCols={[]}
        schema={SCHEMA}
        onBrush={onBrush}
      />,
    );

    // Find the first axis overlay rect (used for brush interaction)
    const brushAreas = container.querySelectorAll("[data-testid='brush-area']");
    expect(brushAreas.length).toBeGreaterThan(0);
    const area = brushAreas[0]; // loss axis

    // Simulate brush: mousedown at top, mousemove partway, mouseup
    // The axis renders from y=20 (top/max) to y=280 (bottom/min) in a 300px-high SVG.
    // loss values: 0.3(row2), 0.5(row1), 0.7(row3). Range: 0.3..0.7
    // Brush from y=20 to y=150 (upper half) selects larger loss values (0.5..0.7)
    fireEvent.mouseDown(area, { clientY: 20 });
    fireEvent.mouseMove(area, { clientY: 150 });
    fireEvent.mouseUp(area, { clientY: 150 });

    expect(onBrush).toHaveBeenCalled();
    const indices: number[] = onBrush.mock.calls[onBrush.mock.calls.length - 1][0];
    expect(Array.isArray(indices)).toBe(true);
    // The brushed region selects rows whose loss falls in the upper portion
    // Rows with loss >= ~0.5 should be included (row 1: 0.5, row 3: 0.7)
    expect(indices).toContain(0); // row index 0 (loss=0.5)
    expect(indices).toContain(2); // row index 2 (loss=0.7)
    expect(indices).not.toContain(1); // row index 1 (loss=0.3) is outside brush
  });

  it("skips rows with null/undefined values for a dimension", () => {
    const rowsWithGap: ExperimentRow[] = [
      makeRow(1, { loss: 0.5, acc: 0.8 }),
      makeRow(2, { acc: 0.9 }), // missing loss
      makeRow(3, { loss: 0.7, acc: 0.7 }),
    ];
    const { container } = render(
      <ParallelCoordinates
        rows={rowsWithGap}
        metricCols={["loss", "acc"]}
        paramCols={[]}
        schema={SCHEMA}
      />,
    );
    const lines = container.querySelectorAll("[data-testid='row-line']");
    expect(lines).toHaveLength(3);
    // Row 2 (index 1) should have a path that skips the loss axis
    // It should use M (moveTo) to jump to the acc axis instead of L (lineTo)
    const row2Path = lines[1].getAttribute("d") ?? "";
    // A complete line with 2 axes would be "M...L...", a gap means only "M..."
    const moveCommands = row2Path.split("M").length - 1;
    // With a gap, the path should have multiple M commands (one per contiguous segment)
    // or a single M with no L (only one valid axis)
    const lineCommands = row2Path.split("L").length - 1;
    // Row 2 only has acc (1 dimension with data), so 1 M command, 0 L commands
    expect(moveCommands).toBe(1);
    expect(lineCommands).toBe(0);
  });

  it("uses canvas when rows exceed 500", () => {
    const manyRows = Array.from({ length: 501 }, (_, i) =>
      makeRow(i + 1, { loss: Math.random(), acc: Math.random() }),
    );

    // Mock canvas getContext
    const mockCtx = {
      clearRect: vi.fn(),
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      set strokeStyle(_: string) {},
      set globalAlpha(_: number) {},
      set lineWidth(_: number) {},
    };
    const origGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue(mockCtx) as unknown as typeof origGetContext;

    try {
      const { container } = render(
        <ParallelCoordinates
          rows={manyRows}
          metricCols={["loss", "acc"]}
          paramCols={[]}
          schema={null}
        />,
      );
      // Should render a canvas element instead of SVG polylines
      expect(container.querySelector("canvas")).toBeInTheDocument();
      // Canvas drawing functions should have been called
      expect(mockCtx.beginPath).toHaveBeenCalled();
      expect(mockCtx.moveTo).toHaveBeenCalled();
      expect(mockCtx.stroke).toHaveBeenCalled();
    } finally {
      HTMLCanvasElement.prototype.getContext = origGetContext;
    }
  });
});
