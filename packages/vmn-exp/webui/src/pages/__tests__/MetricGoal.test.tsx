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
  describe("MIN_LIKE regex returns min", () => {
    it.each(["val_loss", "loss", "train_loss", "rmse", "mse", "mae", "error", "perplexity", "ppl"])(
      "%s -> min",
      (key) => expect(metricGoal(null, key)).toBe("min"),
    );
  });

  describe("MAX_LIKE regex returns max", () => {
    it.each(["val_acc", "accuracy", "f1", "auc", "precision", "recall", "map", "bleu", "rouge", "r2", "iou", "dice", "score", "reward"])(
      "%s -> max",
      (key) => expect(metricGoal(null, key)).toBe("max"),
    );
  });

  describe("unknown keys return null", () => {
    it.each(["seed", "batch_size", "grad_norm_l000", "lr_now", "steps", "epoch", "temperature"])(
      "%s -> null",
      (key) => expect(metricGoal(null, key)).toBeNull(),
    );
  });

  describe("schema goal beats regex", () => {
    it("schema min overrides MAX_LIKE", () => {
      expect(metricGoal({ accuracy: { goal: "min" } }, "accuracy")).toBe("min");
    });

    it("schema max overrides MIN_LIKE", () => {
      expect(metricGoal({ loss: { goal: "max" } }, "loss")).toBe("max");
    });

    it("schema entry without goal on an unknown key returns null", () => {
      expect(metricGoal({ seed: {} }, "seed")).toBeNull();
    });

    it("schema entry without goal on a MIN_LIKE key still returns min", () => {
      expect(metricGoal({ loss: {} }, "loss")).toBe("min");
    });

    it("schema entry without goal on a MAX_LIKE key still returns max", () => {
      expect(metricGoal({ f1: {} }, "f1")).toBe("max");
    });
  });
});

describe("MetricsCard goal arrow", () => {
  it("shows down arrow for min-goal metric", () => {
    render(<MetricsCard metrics={{ loss: 0.5 }} schema={null} />);
    expect(screen.getByText("↓")).toBeTruthy();
  });

  it("shows up arrow for max-goal metric", () => {
    render(<MetricsCard metrics={{ accuracy: 0.9 }} schema={null} />);
    expect(screen.getByText("↑")).toBeTruthy();
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
    // epoch is not min-like or max-like, so goal is null, best should be null
    expect(rows.find((r) => r.key === "epoch")!.best).toBeNull();
  });

  it("still highlights best for known-goal metrics", () => {
    const runs = [
      detail("a", {}, { loss: 0.3, acc: 0.8 }),
      detail("b", {}, { loss: 0.5, acc: 0.9 }),
    ];
    const rows = compareRows(runs, "metrics", null);
    expect(rows.find((r) => r.key === "loss")!.best).toBe(0.3);
    expect(rows.find((r) => r.key === "acc")!.best).toBe(0.9);
  });
});
