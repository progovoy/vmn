import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ParallelCoordinates from "../ParallelCoordinates";
import { colorScale } from "../../util/parallelData";
import type { ExperimentRow, MetricsSchema } from "../../types";

function row(i: number, metrics: Record<string, number>, params: Record<string, unknown> = {}): ExperimentRow {
  return {
    idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null,
    branch: "main", base_version: "0.0.1", user_meta: null, params, metrics,
  };
}

// loss t: 0.5, 0, 1 — acc t: 0.5, 1, 0 (axis spans y=20..280)
const ROWS = [
  row(1, { loss: 0.5, acc: 0.8 }),
  row(2, { loss: 0.3, acc: 0.9 }),
  row(3, { loss: 0.7, acc: 0.7 }),
];
const SCHEMA: MetricsSchema = { loss: { goal: "min" }, acc: { goal: "max", primary: true } };

function drag(area: Element, from: number, to: number) {
  fireEvent.mouseDown(area, { clientY: from });
  fireEvent.mouseMove(window, { clientY: to });
  fireEvent.mouseUp(window);
}

const renderPC = (onBrush = vi.fn(), rows = ROWS, paramCols: string[] = []) => {
  const utils = render(
    <ParallelCoordinates rows={rows} metricCols={["loss", "acc"]} paramCols={paramCols}
      schema={SCHEMA} onBrush={onBrush} />,
  );
  return { ...utils, areas: utils.container.querySelectorAll("[data-testid='brush-area']") };
};

afterEach(() => vi.restoreAllMocks());

describe("ParallelCoordinates multi-brush", () => {
  it("ANDs brushes on several axes", () => {
    const onBrush = vi.fn();
    const { areas } = renderPC(onBrush);
    drag(areas[0], 20, 150); // loss upper half: rows 0, 2
    expect(onBrush).toHaveBeenLastCalledWith([0, 2]);
    drag(areas[1], 200, 290); // acc bottom: row 2
    expect(onBrush).toHaveBeenLastCalledWith([2]);
    expect(screen.getByText(/1 of 3 selected/)).toBeInTheDocument();
  });

  it("a click on an axis clears only that axis's brush", () => {
    const onBrush = vi.fn();
    const { areas } = renderPC(onBrush);
    drag(areas[0], 20, 150);
    drag(areas[1], 200, 290);
    drag(areas[1], 100, 100);
    expect(onBrush).toHaveBeenLastCalledWith([0, 2]);
    drag(areas[0], 50, 51);
    expect(onBrush).toHaveBeenLastCalledWith(null);
    expect(screen.queryByText(/selected/)).toBeNull();
  });

  it("drags through window listeners and removes them on mouseup", () => {
    const remove = vi.spyOn(window, "removeEventListener");
    const onBrush = vi.fn();
    const { areas } = renderPC(onBrush);
    drag(areas[0], 20, 150);
    expect(onBrush).toHaveBeenCalledTimes(1);
    expect(remove.mock.calls.map((c) => c[0])).toEqual(expect.arrayContaining(["mousemove", "mouseup"]));
  });

  it("throttles drag redraws to one per animation frame", () => {
    const raf = vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 1);
    const { areas } = renderPC();
    fireEvent.mouseDown(areas[0], { clientY: 20 });
    fireEvent.mouseMove(window, { clientY: 60 });
    fireEvent.mouseMove(window, { clientY: 90 });
    fireEvent.mouseMove(window, { clientY: 120 });
    expect(raf).toHaveBeenCalledTimes(1);
    fireEvent.mouseUp(window);
  });
});

describe("ParallelCoordinates colouring", () => {
  const strokes = (c: HTMLElement) =>
    [...c.querySelectorAll("[data-testid='row-line']")].map((p) => p.getAttribute("stroke"));

  it("colours by the primary metric with the best run at the top of the scale", () => {
    const { container } = renderPC();
    expect(strokes(container)[1]).toBe(colorScale(1)); // acc 0.9
    expect(strokes(container)[2]).toBe(colorScale(0)); // acc 0.7
  });

  it("recolours by another target metric, honouring its goal", () => {
    const { container } = renderPC();
    fireEvent.change(screen.getByLabelText("color by"), { target: { value: "loss" } });
    expect(strokes(container)[1]).toBe(colorScale(1)); // loss 0.3 is best
    expect(strokes(container)[2]).toBe(colorScale(0));
  });
});

describe("ParallelCoordinates categorical params", () => {
  it("draws a labelled categorical axis instead of dropping the param", () => {
    const rows = [row(1, { loss: 0.5, acc: 0.8 }, { model: "vit" }), row(2, { loss: 0.3, acc: 0.9 }, { model: "resnet" })];
    const { container } = renderPC(vi.fn(), rows, ["model"]);
    expect(container.querySelectorAll("[data-testid='axis']")).toHaveLength(3);
    expect(screen.getByText("vit")).toBeInTheDocument();
    expect(screen.getByText("resnet")).toBeInTheDocument();
    const paths = [...container.querySelectorAll("[data-testid='row-line']")];
    for (const p of paths) expect((p.getAttribute("d") ?? "").split("L")).toHaveLength(3);
  });
});

describe("ParallelCoordinates canvas", () => {
  it("scales the backing store by devicePixelRatio", () => {
    vi.spyOn(window, "devicePixelRatio", "get").mockReturnValue(2);
    const ctx = {
      clearRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(),
      stroke: vi.fn(), save: vi.fn(), restore: vi.fn(),
      set strokeStyle(_: string) {}, set globalAlpha(_: number) {}, set lineWidth(_: number) {},
    };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as unknown as CanvasRenderingContext2D);
    const rows = Array.from({ length: 501 }, (_, i) => row(i + 1, { loss: i, acc: i }));
    const { container } = renderPC(vi.fn(), rows);
    const canvas = container.querySelector("canvas")!;
    expect(canvas.width).toBe(600);
    expect(canvas.style.width).toBe("300px");
    // coordinates are drawn in device pixels: the top of an axis is y = 20 * 2
    expect(ctx.moveTo.mock.calls.some(([, y]) => y === 40)).toBe(true);
  });
});

it("is memoized", () => {
  expect((ParallelCoordinates as unknown as { $$typeof: symbol }).$$typeof).toBe(Symbol.for("react.memo"));
});
