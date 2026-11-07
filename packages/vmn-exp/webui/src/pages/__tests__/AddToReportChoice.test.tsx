// Plan 32: "Add to report" saves what the reader sees, not the chart's defaults.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("uplot", async () => await import("../../components/__tests__/fakeUPlot"));
vi.mock("../../reports/AddToReport", async () => {
  const { useState } = await import("react");
  return {
    default: ({ spec }: { spec: () => unknown }) => {
      const [saved, setSaved] = useState<unknown>(null);
      return <button type="button" data-spec={JSON.stringify(saved)} onClick={() => setSaved(spec())}>Add to report</button>;
    },
  };
});
vi.mock("../../api", () => ({
  api: { experimentsImportance: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  appTag: (a: string) => a.replaceAll("/", "-"),
}));

import { api } from "../../api";
import { enableCanvas } from "../../components/__tests__/fakeUPlot";
import LeaderboardCharts from "../LeaderboardCharts";
import type { ChartView } from "../../hooks/useLeaderboardView";

const rows = [
  { idx: 1, verstr: "a", branch: "main", params: { lr: 0.1 }, metrics: { loss: 0.5, acc: 0.8 } },
  { idx: 2, verstr: "b", branch: "main", params: { lr: 0.2 }, metrics: { loss: 0.3, acc: 0.9 } },
] as never[];

const charts = (view: ChartView) => renderWithClient(
  <MemoryRouter>
    <LeaderboardCharts view={view} onView={() => {}} rows={rows} metricCols={["loss", "acc"]} paramCols={["lr"]}
      schema={null} onBrush={() => {}}
      importance={{ ws: "w", app: "my-app", filter: { query: "metrics.loss < 1" }, defaultMetric: "acc" }} />
  </MemoryRouter>,
);

/** The `n`th picker of the chart (the chart-type control is buttons, not a combobox). */
const pick = async (n: number, value: string) => {
  const boxes = await screen.findAllByRole("combobox");
  fireEvent.change(boxes[n], { target: { value } });
};
const saved = () => {
  fireEvent.click(screen.getByRole("button", { name: "Add to report" }));
  return JSON.parse(screen.getByRole("button", { name: "Add to report" }).getAttribute("data-spec")!);
};

beforeEach(() => {
  vi.clearAllMocks();
  enableCanvas();
  (api.experimentsImportance as ReturnType<typeof vi.fn>).mockResolvedValue([]);
});

describe("Add to report saves the reader's choices", () => {
  it("bar: the picked metric", async () => {
    charts("bar");
    await pick(0, "acc");
    expect(saved()).toMatchObject({ type: "bar", metric: "acc" });
  });

  it("scatter: the picked axes, a param as params.<name>", async () => {
    charts("scatter");
    await pick(0, "lr");
    await pick(1, "loss");
    expect(saved()).toMatchObject({ type: "scatter", x: "params.lr", y: "loss" });
  });

  it("grouped: the picked group and metric", async () => {
    charts("grouped");
    await pick(0, "lr");
    await pick(1, "acc");
    expect(saved()).toMatchObject({ type: "grouped", group_by: "params.lr", metric: "acc" });
  });

  it("importance: the picked target metric", async () => {
    charts("importance");
    await pick(0, "loss");
    expect(saved()).toMatchObject({ type: "importance", metric: "loss" });
  });
});
