import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import TrainingCurves from "../TrainingCurves";
import { MAX_OVERLAY_SERIES } from "../GlobOverlay";
import { renderWithClient } from "../../test-utils";
import type { SeriesPoint } from "../../types";

const pts = (n: number): SeriesPoint[] =>
  Array.from({ length: n }, (_, i) => ({ step: i, value: 1 / (i + 1), ts: null }));

const folds = (n: number) =>
  Object.fromEntries(Array.from({ length: n }, (_, i) => [`cv${i}.grad_norm_mean`, pts(5)]));

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

const overlayInput = () => screen.getByRole("searchbox", { name: /overlay metrics/i });

describe("the Run page overlay", () => {
  it("draws every key a glob matches in one chart", async () => {
    renderWithClient(<TrainingCurves series={{ ...folds(3), loss: pts(5) }} />);
    await waitFor(() => expect(instances).toHaveLength(4));
    fireEvent.change(overlayInput(), { target: { value: "cv*.grad_norm_mean" } });
    const card = await screen.findByTestId("overlay-chart");
    expect(card.getAttribute("data-keys")).toBe("cv0.grad_norm_mean,cv1.grad_norm_mean,cv2.grad_norm_mean");
    await waitFor(() => expect(instances).toHaveLength(5));
    expect((instances[4].opts.series as unknown[]).length).toBe(4);
  });

  it("caps the overlay and says so", async () => {
    renderWithClient(<TrainingCurves series={folds(MAX_OVERLAY_SERIES + 5)} />);
    fireEvent.change(overlayInput(), { target: { value: "cv*" } });
    const card = await screen.findByTestId("overlay-chart");
    expect(card.getAttribute("data-keys")!.split(",")).toHaveLength(MAX_OVERLAY_SERIES);
    expect(screen.getByText(`showing ${MAX_OVERLAY_SERIES} of ${MAX_OVERLAY_SERIES + 5} matches`)).toBeInTheDocument();
  });

  it("follows log y", async () => {
    renderWithClient(<TrainingCurves series={folds(2)} />);
    fireEvent.change(overlayInput(), { target: { value: "cv*" } });
    await screen.findByTestId("overlay-chart");
    fireEvent.click(screen.getByRole("button", { name: /log y/i }));
    await waitFor(() => {
      const last = instances[instances.length - 1];
      expect((last.opts.scales as { y: { distr: number } }).y.distr).toBe(3);
    });
  });

  it("says when the glob matches nothing", async () => {
    renderWithClient(<TrainingCurves series={folds(2)} />);
    fireEvent.change(overlayInput(), { target: { value: "nope*" } });
    expect(await screen.findByText(/No metric matches the overlay/)).toBeInTheDocument();
    expect(screen.queryByTestId("overlay-chart")).toBeNull();
  });

  it("survives a pattern that is no valid range", async () => {
    renderWithClient(<TrainingCurves series={folds(2)} />);
    fireEvent.change(overlayInput(), { target: { value: "cv[z-a]" } });
    expect(await screen.findByText(/No metric matches the overlay/)).toBeInTheDocument();
  });
});
