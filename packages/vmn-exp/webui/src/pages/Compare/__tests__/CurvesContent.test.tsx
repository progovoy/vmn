/** M2 on the Curves tab: the legend names runs `@N name` (verstr in the
 *  title, a copy button); one labelled "x axis" control step / wall /
 *  relative / <metric>; Log y a pressed chip; smoothing shows its value. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("uplot", async () => await import("../../../components/__tests__/fakeUPlot"));
vi.mock("../../../api", () => ({
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../../apiSeries", () => ({
  fetchSeriesBatch: vi.fn(),
  fetchRunStatuses: vi.fn(),
}));

import { fetchRunStatuses, fetchSeriesBatch } from "../../../apiSeries";
import { enableCanvas, resetInstances } from "../../../components/__tests__/fakeUPlot";
import ComparePage from "../ComparePage";

const mockedBatch = fetchSeriesBatch as unknown as ReturnType<typeof vi.fn>;
const mockedStatuses = fetchRunStatuses as unknown as ReturnType<typeof vi.fn>;

const RUNS = ["0.0.1-dev.a", "0.0.1-dev.b"];
const curve = () => [0, 1, 2].map((i) => ({ step: i, value: 1 - i * 0.1, ts: 1_700_000_000 + i }));

function renderCurves() {
  mockedBatch.mockResolvedValue({
    series: Object.fromEntries(RUNS.map((v) => [v, { loss: curve(), epoch: curve() }])),
    series_total: {}, step_metrics: {}, missing: [],
  });
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/w/app/my-app/compare-runs?${RUNS.map((r) => `sel=${r}`).join("&")}`]}>
      <Routes><Route path="/ws/:ws/app/:app/compare-runs" element={<ComparePage />} /></Routes>
    </MemoryRouter>,
  );
}

const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  vi.clearAllMocks();
  resetInstances();
  enableCanvas();
  mockedStatuses.mockResolvedValue({
    [RUNS[0]]: { verstr: RUNS[0], idx: 1, name: "baseline" },
    [RUNS[1]]: { verstr: RUNS[1], idx: 2, name: null },
  });
});
afterEach(() => {
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

const xAxis = () => screen.getByRole("group", { name: "x axis" });
const pressed = (name: string) => within(xAxis()).getByRole("button", { name }).getAttribute("aria-pressed");

describe("Compare curves legend", () => {
  it("names each run @N name, verstr in the title, with a copy button", async () => {
    renderCurves();
    const entry = await screen.findByRole("button", { name: "@1 baseline" });
    expect(entry).toHaveAttribute("title", RUNS[0]);
    expect(screen.getByRole("button", { name: "@2" })).toHaveAttribute("title", RUNS[1]);
    expect(screen.getByRole("button", { name: `copy ${RUNS[0]}` })).toBeInTheDocument();
  });
});

describe("Compare curves x axis", () => {
  it("is one labelled control: step, wall, relative and a metric", async () => {
    renderCurves();
    await screen.findByText("loss");
    expect(xAxis()).toHaveTextContent(/^x axis/);
    expect(pressed("Step")).toBe("true");
    expect(pressed("Wall")).toBe("false");
    expect(pressed("Relative")).toBe("false");
    expect(within(xAxis()).getByRole("combobox", { name: /x axis metric/i })).toHaveValue("");
  });

  it("picking a metric releases step; picking wall clears the metric", async () => {
    renderCurves();
    await screen.findByText("loss");
    const pick = within(xAxis()).getByRole("combobox", { name: /x axis metric/i });
    fireEvent.change(pick, { target: { value: "epoch" } });
    await waitFor(() => expect(pressed("Step")).toBe("false"));
    expect(pick).toHaveValue("epoch");
    expect(pick.closest(".select-wrap")).toHaveClass("on");
    fireEvent.click(within(xAxis()).getByRole("button", { name: "Wall" }));
    expect(pressed("Wall")).toBe("true");
    expect(pick).toHaveValue("");
    expect(pick.closest(".select-wrap")).not.toHaveClass("on");
  });

  it("step after a metric goes back to the step axis", async () => {
    renderCurves();
    await screen.findByText("loss");
    const pick = within(xAxis()).getByRole("combobox", { name: /x axis metric/i });
    fireEvent.change(pick, { target: { value: "epoch" } });
    fireEvent.click(within(xAxis()).getByRole("button", { name: "Step" }));
    expect(pressed("Step")).toBe("true");
    expect(pick).toHaveValue("");
  });
});

describe("Compare curves Log y and smoothing", () => {
  it("Log y is a chip whose on state is pressed", async () => {
    renderCurves();
    await screen.findByText("loss");
    const log = screen.getByRole("button", { name: "Log y" });
    expect(log).toHaveAttribute("aria-pressed", "false");
    expect(log).toHaveClass("status-toggle");
    fireEvent.click(log);
    expect(screen.getByRole("button", { name: "Log y" })).toHaveAttribute("aria-pressed", "true");
  });

  it("smoothing shows its value, off at zero", async () => {
    renderCurves();
    await screen.findByText("loss");
    const slider = screen.getByRole("slider", { name: /smoothing/i });
    expect(slider).toHaveAttribute("aria-valuetext", "off");
    expect(slider.closest("label")).toHaveTextContent(/smoothing\s*off/);
    fireEvent.change(slider, { target: { value: "0.6" } });
    expect(slider).toHaveAttribute("aria-valuetext", "0.6");
    expect(slider.closest("label")).toHaveTextContent(/smoothing\s*0\.6/);
  });
});
