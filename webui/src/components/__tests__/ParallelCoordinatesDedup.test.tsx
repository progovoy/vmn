import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import ParallelCoordinates from "../ParallelCoordinates";
import { metricColumns, paramKey } from "../../pages/leaderboardColumns";
import type { ExperimentRow } from "../../types";

function row(
  idx: number,
  metrics: Record<string, number>,
  params: Record<string, unknown>,
): ExperimentRow {
  return {
    idx, verstr: `v${idx}`, code_verstr: `v${idx}`, timestamp: null, note: null,
    branch: "main", base_version: "0.0.1", user_meta: null, params, metrics,
  };
}

// `lr` folds into both `params` and `metrics` (server-side, intentional).
// Fed through the real column-building helpers, it must reach the chart as
// exactly one axis — categorized as a param, not duplicated as a metric too.
const ROWS = [
  row(1, { loss: 0.5, lr: 0.01 }, { lr: 0.01 }),
  row(2, { loss: 0.3, lr: 0.02 }, { lr: 0.02 }),
];

describe("ParallelCoordinates renders a deduped axis for a folded param", () => {
  it("draws one axis per key, not two for a key present in both sets", () => {
    const metricCols = metricColumns(ROWS, null);
    const paramCols = paramKey(ROWS) ? paramKey(ROWS).split("\u0000") : [];
    expect(metricCols).toEqual(["loss"]);
    expect(paramCols).toEqual(["lr"]);

    const { container } = render(
      <ParallelCoordinates rows={ROWS} metricCols={metricCols} paramCols={paramCols} schema={null} />,
    );
    expect(container.querySelectorAll("[data-testid='axis']")).toHaveLength(2);
    const axisLabels = [...container.querySelectorAll("svg text")].map((a) => a.textContent);
    expect(axisLabels.filter((l) => l === "lr")).toHaveLength(1);
    expect(axisLabels.filter((l) => l === "loss")).toHaveLength(1);
  });
});
