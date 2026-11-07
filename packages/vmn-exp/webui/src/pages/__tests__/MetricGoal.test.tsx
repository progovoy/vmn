import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { metricGoal } from "../../util";
import { MetricsCard } from "../RunSections";
import { compareRows } from "../compareRunsData";
import type { ExperimentDetail } from "../../types";

const detail = (
  verstr: string, params: Record<string, unknown>, metrics: ExperimentDetail["metrics"],
): ExperimentDetail => ({
  metadata: { verstr }, params, metrics, series: {}, patches: {},
});

describe("metricGoal", () => {
  it.each(["val_loss", "loss", "rmse", "val_acc", "accuracy", "f1", "seed"])(
    "%s without a declared goal -> null (never guessed from the name)",
    (key) => expect(metricGoal(null, key)).toBeNull(),
  );

  it("reads the goal the schema declares for the exact name", () => {
    expect(metricGoal({ accuracy: { goal: "min" } }, "accuracy")).toBe("min");
    expect(metricGoal({ loss: { goal: "max" } }, "loss")).toBe("max");
  });

  it("a schema entry without a goal has none", () => {
    expect(metricGoal({ loss: {} }, "loss")).toBeNull();
    expect(metricGoal({ f1: { goal: "up" } }, "f1")).toBeNull();
  });
});

describe("MetricsCard goal arrow", () => {
  it("shows down arrow for min-goal metric", () => {
    render(<MetricsCard metrics={{ loss: 0.5 }} schema={{ loss: { goal: "min" } }} />);
    expect(screen.getByText("↓")).toBeTruthy();
  });

  it("shows up arrow for max-goal metric", () => {
    render(<MetricsCard metrics={{ accuracy: 0.9 }} schema={{ accuracy: { goal: "max" } }} />);
    expect(screen.getByText("↑")).toBeTruthy();
  });

  it("shows no arrow for a loss-like name without a declared goal", () => {
    render(<MetricsCard metrics={{ loss: 0.5, accuracy: 0.9 }} schema={null} />);
    expect(screen.queryByText("↓")).toBeNull();
    expect(screen.queryByText("↑")).toBeNull();
  });

  it("shows no arrow for null-goal metric", () => {
    render(<MetricsCard metrics={{ seed: 42 }} schema={null} />);
    expect(screen.queryByText("↓")).toBeNull();
    expect(screen.queryByText("↑")).toBeNull();
  });
});

describe("compareRows with null-goal metrics", () => {
  it("returns null best when the metric has no goal", () => {
    const runs = [
      detail("a", {}, { epoch: 10 }),
      detail("b", {}, { epoch: 20 }),
    ];
    const rows = compareRows(runs, "metrics", null);
    expect(rows.find((r) => r.key === "epoch")!.best).toBeNull();
  });

  it("returns null best for a loss-like name without a declared goal", () => {
    const runs = [detail("a", {}, { loss: 0.3 }), detail("b", {}, { loss: 0.5 })];
    expect(compareRows(runs, "metrics", null).find((r) => r.key === "loss")!.best).toBeNull();
  });

  it("highlights best for declared-goal metrics", () => {
    const runs = [
      detail("a", {}, { loss: 0.3, acc: 0.8 }),
      detail("b", {}, { loss: 0.5, acc: 0.9 }),
    ];
    const rows = compareRows(runs, "metrics", { loss: { goal: "min" }, acc: { goal: "max" } });
    expect(rows.find((r) => r.key === "loss")!.best).toBe(0.3);
    expect(rows.find((r) => r.key === "acc")!.best).toBe(0.9);
  });
});
