import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createQueryClient } from "../../queryClient";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import FakeUPlot, { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import TrainingCurves from "../TrainingCurves";
import { renderWithClient } from "../../test-utils";
import type { SeriesPoint } from "../../types";

const pts = (n: number, f: (i: number) => number): SeriesPoint[] =>
  Array.from({ length: n }, (_, i) => ({ step: i, value: f(i), ts: null }));

const SERIES = { loss: pts(6, (i) => 1 / (i + 1)), epoch: pts(6, (i) => Math.floor(i / 2)) };

const originalMatchMedia = window.matchMedia;
const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  resetInstances();
  enableCanvas();
});
afterEach(() => {
  window.matchMedia = originalMatchMedia;
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

const logButton = () => screen.getByRole("button", { name: /log y/i });

/** Every y array the newest plot was last given. */
function plottedYs(u: FakeUPlot): number[][] {
  const calls = u.setData.mock.calls;
  const data = (calls.length ? calls[calls.length - 1][0] : u.data) as [null, ...[Float64Array, Float64Array][]];
  return data.slice(1).map((s) => Array.from((s as [Float64Array, Float64Array])[1]));
}

describe("TrainingCurves controlled", () => {
  it("follows controlled logY and reports toggles without changing itself", () => {
    const onChange = vi.fn();
    renderWithClient(<TrainingCurves series={SERIES} controls={{ logY: true }} onControlsChange={onChange} />);
    expect(logButton()).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(logButton());
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ logY: false }));
    expect(logButton()).toHaveAttribute("aria-pressed", "true");
  });

  it("re-renders when the controlled value changes", () => {
    const client = createQueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { rerender } = render(<TrainingCurves series={SERIES} controls={{ logY: false }} />, { wrapper });
    expect(logButton()).toHaveAttribute("aria-pressed", "false");
    rerender(<TrainingCurves series={SERIES} controls={{ logY: true }} />);
    expect(logButton()).toHaveAttribute("aria-pressed", "true");
  });

  it("starts from defaultControls and stays uncontrolled", () => {
    const onChange = vi.fn();
    renderWithClient(<TrainingCurves series={SERIES} defaultControls={{ logY: true }} onControlsChange={onChange} />);
    expect(logButton()).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(logButton());
    expect(logButton()).toHaveAttribute("aria-pressed", "false");
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ logY: false }));
  });

  it("a controlled x metric joins every training metric on it", async () => {
    const fetchJoined = vi.fn().mockResolvedValue({});
    renderWithClient(<TrainingCurves series={SERIES} fetchJoined={fetchJoined} controls={{ x: "epoch" }} />);
    await waitFor(() => expect(fetchJoined).toHaveBeenCalledWith({ loss: "epoch" }));
    expect(screen.getByRole("combobox", { name: /x axis metric/i })).toHaveValue("epoch");
  });

  it("a controlled smoothing value smooths the drawn curve", async () => {
    renderWithClient(<TrainingCurves series={{ loss: SERIES.loss }} controls={{ smoothing: 0.9 }} />);
    await waitFor(() => expect(instances.length).toBeGreaterThan(0));
    const ys = plottedYs(instances[instances.length - 1]);
    expect(ys.some((y) => y[5] > 0.5)).toBe(true); // raw last value is 1/6
  });
});
