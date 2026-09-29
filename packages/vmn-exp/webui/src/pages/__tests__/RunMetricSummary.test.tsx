import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MetricsCard } from "../RunSections";
import { summaryFromDetail } from "../runSummary";
import type { ExperimentDetail } from "../../types";

const OVERFIT = { last: 0.9, min: 0.2, max: 1 };

describe("MetricsCard best-value summaries", () => {
  it("shows the best value with last/min/max beside it", () => {
    render(
      <MetricsCard
        metrics={{ loss: 0.2 }}
        summary={{ loss: OVERFIT }}
        schema={{ loss: { goal: "min" } }}
      />,
    );
    expect(screen.getByTestId("metric-value-loss").textContent).toBe("0.2");
    expect(screen.getByTestId("metric-summary-loss").textContent).toBe(
      "last 0.9 · min 0.2 · max 1",
    );
  });

  it("omits the summary line for a metric logged once", () => {
    render(<MetricsCard metrics={{ acc: 0.95 }} summary={{}} schema={null} />);
    expect(screen.getByTestId("metric-value-acc").textContent).toBe("0.95");
    expect(screen.queryByTestId("metric-summary-acc")).toBeNull();
  });

  it("works without any summary (an older server)", () => {
    render(<MetricsCard metrics={{ acc: 0.95 }} schema={null} />);
    expect(screen.queryByTestId("metric-summary-acc")).toBeNull();
  });

  it("labels the card as metrics, not final values", () => {
    render(<MetricsCard metrics={{ loss: 0.2 }} summary={{ loss: OVERFIT }} schema={null} />);
    expect(screen.queryByText("final metrics")).toBeNull();
    expect(screen.getByText("metrics")).toBeTruthy();
  });
});

describe("summaryFromDetail", () => {
  it("carries the detail's metric_summary", () => {
    const detail = {
      metadata: { verstr: "0.0.1" },
      metrics: { loss: 0.2 },
      metric_summary: { loss: OVERFIT },
      series: {},
      patches: {},
    } as unknown as ExperimentDetail;
    expect(summaryFromDetail(detail).metricSummary).toEqual({ loss: OVERFIT });
  });
});
