/** MetricScatter driven from outside (plan 23 W4, the job Charts tab keeps its
 *  axes in the URL): controlled axes, a metric-only Y picker, and hover/click
 *  over many points through the grid lookup. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import MetricScatter from "../MetricScatter";
import type { ExperimentRow } from "../../types";

const originalMatchMedia = window.matchMedia;
const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => { resetInstances(); enableCanvas(); });
afterEach(() => {
  window.matchMedia = originalMatchMedia;
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

const row = (i: number, lr: number, loss: number): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null, branch: null,
  base_version: null, params: { lr }, metrics: { loss, acc: 1 - loss },
});

const ROWS = Array.from({ length: 5000 }, (_, i) => row(i, i, (i % 100) / 100));

describe("MetricScatter, controlled", () => {
  it("plots the given axes and reports picks instead of keeping them", async () => {
    const onAxes = vi.fn();
    render(
      <MetricScatter rows={ROWS} metricCols={["loss", "acc"]} paramCols={["lr"]} schema={null}
        x="lr" y="loss" yCols={["loss", "acc"]} onAxes={onAxes} />,
    );
    const [xSel, ySel] = screen.getAllByRole("combobox") as HTMLSelectElement[];
    expect([xSel.value, ySel.value]).toEqual(["lr", "loss"]);
    expect([...ySel.options].map((o) => o.value)).toEqual(["loss", "acc"]);
    fireEvent.change(ySel, { target: { value: "acc" } });
    expect(onAxes).toHaveBeenCalledWith("lr", "acc");
    // Controlled: the pick waits for the parent.
    expect(ySel.value).toBe("loss");
  });

  it("names the hovered run and opens it on click", async () => {
    const onSelect = vi.fn();
    render(
      <MetricScatter rows={ROWS} metricCols={["loss"]} paramCols={["lr"]} schema={null}
        x="lr" y="loss" onAxes={() => {}} onSelect={onSelect} />,
    );
    await waitFor(() => expect(instances.length).toBeGreaterThan(0));
    // The fake maps pixels to values one to one: (1234, 0.34) is run 1234.
    act(() => instances[instances.length - 1].moveCursor(1234, 0.34));
    expect(await screen.findByTestId("scatter-tooltip")).toHaveTextContent("@1234");
    fireEvent.click(screen.getByTestId("scatter-chart"));
    expect(onSelect).toHaveBeenCalledWith("v1234");
  });
});
