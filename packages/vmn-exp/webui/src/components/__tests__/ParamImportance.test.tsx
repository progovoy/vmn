import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("../../api", () => ({ api: { experimentsImportance: vi.fn() } }));
vi.mock("../MetricScatter", () => ({
  default: ({ initialX, initialY, rows }: { initialX?: string; initialY?: string; rows: unknown[] }) => (
    <div>scatter:{initialX}:{initialY}:{rows.length}</div>
  ),
}));

import { api } from "../../api";
import { renderWithClient } from "../../test-utils";
import ParamImportance from "../ParamImportance";
import type { ExperimentRow } from "../../types";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const ENTRIES = [
  { param: "lr", importance: 0.8, correlation: 0.9, spearman: 0.88, kind: "numeric", n: 40 },
  { param: "dropout", importance: 0.15, correlation: -0.4, spearman: -0.35, kind: "numeric", n: 40 },
  { param: "opt", importance: 0.05, correlation: null, spearman: null, kind: "categorical", n: 38 },
];

const row = (i: number, loss: number, params: Record<string, unknown>): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null, branch: null,
  base_version: null, params, metrics: { loss, acc: 1 - loss },
});
const ROWS = [
  row(1, 0.2, { lr: 1, opt: "adam" }),
  row(2, 0.4, { lr: 2, opt: "adam" }),
  row(3, 0.9, { lr: 3, opt: "sgd" }),
];

function renderPanel(props: Partial<Parameters<typeof ParamImportance>[0]> = {}) {
  return renderWithClient(
    <ParamImportance
      ws="w" app="my-app" filter={{ status: "failed", query: "params.lr > 0" }}
      rows={ROWS} metricCols={["loss", "acc"]} paramCols={["lr", "dropout", "opt"]}
      schema={{}} defaultMetric="acc" {...props}
    />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  m.experimentsImportance.mockResolvedValue(ENTRIES);
});

describe("ParamImportance", () => {
  it("asks for the default metric under the leaderboard filter", async () => {
    renderPanel();
    await screen.findByText("lr");
    expect(m.experimentsImportance).toHaveBeenCalledWith(
      "w", "my-app", "acc", expect.objectContaining({ status: "failed", query: "params.lr > 0" }),
    );
    expect((screen.getByLabelText("target metric") as HTMLSelectElement).value).toBe("acc");
  });

  it("falls back to the first metric without a usable default", async () => {
    renderPanel({ defaultMetric: "nope" });
    await screen.findByText("lr");
    expect(m.experimentsImportance).toHaveBeenCalledWith("w", "my-app", "loss", expect.anything());
  });

  it("lists params in order with importance bars and signed correlations", async () => {
    renderPanel();
    await screen.findByText("lr");
    const names = screen.getAllByTestId("importance-param").map((el) => el.textContent);
    expect(names).toEqual(["lr", "dropout", "opt"]);
    const bars = screen.getAllByTestId("importance-bar") as HTMLElement[];
    expect(bars[0].style.width).toBe("100%"); // scaled to the top param
    expect(bars[1].style.width).toBe("18.75%");
    const corr = screen.getAllByTestId("importance-corr") as HTMLElement[];
    expect(corr[0].textContent).toBe("+0.90");
    expect(corr[0].style.color).toBe("var(--good)");
    expect(corr[1].textContent).toBe("-0.40");
    expect(corr[1].style.color).toBe("var(--bad)");
    expect(corr[2].textContent).toBe("—");
  });

  it("refetches when the target metric changes", async () => {
    renderPanel();
    await screen.findByText("lr");
    fireEvent.change(screen.getByLabelText("target metric"), { target: { value: "loss" } });
    await waitFor(() =>
      expect(m.experimentsImportance).toHaveBeenCalledWith("w", "my-app", "loss", expect.anything()),
    );
  });

  it("clicking a numeric param opens its scatter against the metric", async () => {
    renderPanel();
    fireEvent.click(await screen.findByText("lr"));
    expect(screen.getByText("scatter:lr:acc:3")).toBeInTheDocument();
  });

  it("clicking a categorical param shows the metric's mean per value", async () => {
    renderPanel({ defaultMetric: "loss" });
    fireEvent.click(await screen.findByText("opt"));
    const values = screen.getAllByTestId("importance-value").map((el) => el.textContent);
    expect(values).toEqual(["adam", "sgd"]);
    expect(screen.getByText("0.3")).toBeInTheDocument(); // mean loss of adam
  });

  it("shows the server's message when the request fails", async () => {
    m.experimentsImportance.mockRejectedValue(Object.assign(new Error("Unknown metric 'acc'"), { status: 400 }));
    renderPanel();
    expect(await screen.findByText(/Unknown metric 'acc'/)).toBeInTheDocument();
  });

  it("says so when no param varies", async () => {
    m.experimentsImportance.mockResolvedValue([]);
    renderPanel();
    expect(await screen.findByText(/no param varies/i)).toBeInTheDocument();
  });
});
