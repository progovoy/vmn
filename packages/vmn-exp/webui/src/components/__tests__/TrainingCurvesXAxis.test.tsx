import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, resetInstances } from "./fakeUPlot";
import TrainingCurves from "../TrainingCurves";
import { renderWithClient } from "../../test-utils";
import type { SeriesPoint } from "../../types";

const pts = (n: number, f: (i: number) => number, ts: string | null = null): SeriesPoint[] =>
  Array.from({ length: n }, (_, i) => ({ step: i, value: f(i), ts }));

const SERIES = {
  loss: pts(6, (i) => 1 / (i + 1)),
  val_loss: pts(6, (i) => 2 / (i + 1)),
  epoch: pts(6, (i) => Math.floor(i / 2)),
};

const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  resetInstances();
  enableCanvas();
});
afterEach(() => {
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

const axisGroup = () => screen.getByRole("group", { name: "x axis" });

describe("TrainingCurves x axis control", () => {
  it("is one labelled step / wall / relative / metric control, no 'x: declared' select", () => {
    renderWithClient(<TrainingCurves series={SERIES} />);
    const group = axisGroup();
    for (const name of ["Step", "Wall", "Relative"]) {
      expect(within(group).getByRole("button", { name })).toBeInTheDocument();
    }
    expect(within(group).getByRole("button", { name: "Step" })).toHaveAttribute("aria-pressed", "true");
    const select = within(group).getByRole("combobox", { name: /x axis metric/i }) as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["", "epoch", "loss", "val_loss"]);
    expect(screen.queryByText(/x: declared/)).toBeNull();
  });

  it("disables the time modes when a point has no timestamp, enables them when all do", () => {
    const { unmount } = renderWithClient(<TrainingCurves series={SERIES} />);
    expect(within(axisGroup()).getByRole("button", { name: "Wall" })).toBeDisabled();
    unmount();
    const ts = "2026-01-01T00:00:00Z";
    renderWithClient(<TrainingCurves series={{ loss: pts(3, (i) => i, ts) }} />);
    const wall = within(axisGroup()).getByRole("button", { name: "Wall" });
    expect(wall).toBeEnabled();
    fireEvent.click(wall);
    expect(wall).toHaveAttribute("aria-pressed", "true");
    expect(within(axisGroup()).getByRole("button", { name: "Step" })).toHaveAttribute("aria-pressed", "false");
  });

  it("Step returns a picked metric to each chart's declared step metric", async () => {
    const joinedOn = (xMap: Record<string, string>) => Object.fromEntries(Object.keys(xMap).map(
      (m) => [m, [0, 1].map((i) => ({ step: i, ts: null, value: 1, x: i }))],
    ));
    const fetchJoined = vi.fn().mockImplementation(async (xMap: Record<string, string>) => joinedOn(xMap));
    renderWithClient(<TrainingCurves series={SERIES} stepMetrics={{ val_loss: "epoch" }} fetchJoined={fetchJoined} />);
    expect(await screen.findByText(/vs epoch/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: /x axis metric/i }), { target: { value: "loss" } });
    await waitFor(() => expect(screen.getAllByText(/vs loss/)).toHaveLength(2));
    expect(within(axisGroup()).getByRole("button", { name: "Step" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(within(axisGroup()).getByRole("button", { name: "Step" }));
    expect(screen.getByRole("combobox", { name: /x axis metric/i })).toHaveValue("");
    await waitFor(() => expect(screen.queryByText(/vs loss/)).toBeNull());
    expect(screen.getByText(/vs epoch/)).toBeInTheDocument();
  });

  it("Log y is a pressed/unpressed chip", () => {
    renderWithClient(<TrainingCurves series={SERIES} />);
    const log = screen.getByRole("button", { name: /log y/i });
    expect(log).toHaveClass("status-toggle");
    expect(log).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(log);
    expect(log).toHaveAttribute("aria-pressed", "true");
  });
});
