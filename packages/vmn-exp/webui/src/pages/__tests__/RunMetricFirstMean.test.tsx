import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MetricsCard } from "../RunSections";

describe("MetricsCard first/mean summaries", () => {
  it("shows first and mean beside last/min/max when the server sends them", () => {
    render(
      <MetricsCard
        metrics={{ loss: 0.7 }}
        summary={{ loss: { last: 0.9, min: 0.2, max: 1, first: 1, mean: 0.7 } }}
        schema={{ loss: { summary: "mean" } }}
      />,
    );
    expect(screen.getByTestId("metric-summary-loss").textContent).toBe(
      "last 0.9 · min 0.2 · max 1 · first 1 · mean 0.7",
    );
  });

  it("leaves out a mean with no finite value", () => {
    render(
      <MetricsCard
        metrics={{ loss: 0.9 }}
        summary={{ loss: { last: 0.9, min: 0.2, max: 1, first: 1, mean: null } }}
        schema={null}
      />,
    );
    expect(screen.getByTestId("metric-summary-loss").textContent).toBe(
      "last 0.9 · min 0.2 · max 1 · first 1",
    );
  });
});
