/** The Charts tab's data prep (plan 23 W4): which columns each chart asks
 *  for, the colour-by groups, and the per-value boxes. */
import { describe, it, expect } from "vitest";
import type { ExperimentColumns } from "../../../types";
import { runColor } from "../../../util";
import {
  boxGroups, colorBy, jobChartKeys, jobRows, OTHER_COLOR, PARAM_COLORS, STATUS_COLORS,
} from "../jobChartData";

const COLS: ExperimentColumns = {
  verstrs: ["a", "b", "c", "d"],
  idx: [1, 2, 3, 4],
  total: 4,
  columns: {
    "metrics.loss": [0.5, 0.3, null, 0.9],
    "params.opt": ["adam", "sgd", "adam", null],
    "params.lr": [0.1, 0.01, 0.1, 0.001],
    status: ["succeeded", "failed", "running", "created"],
    name: ["t1", null, "t3", "t4"],
  },
};

describe("jobChartKeys", () => {
  it("asks the scatter for its axes, the colour and the status and name", () => {
    expect(jobChartKeys({ chart: "scatter", x: "params.lr", y: "loss", color: "params.opt", params: ["lr", "opt"] }))
      .toEqual(["params.lr", "metrics.loss", "params.opt", "status", "name"]);
  });

  it("asks parallel coordinates for every param and the metric", () => {
    expect(jobChartKeys({ chart: "parallel", x: "params.lr", y: "loss", color: "status", params: ["lr", "opt"] }))
      .toEqual(["metrics.loss", "params.lr", "params.opt", "status", "name"]);
  });

  it("asks the box chart for the metric and the grouping param only", () => {
    expect(jobChartKeys({ chart: "bypar", x: "params.opt", y: "loss", color: "status", params: ["lr", "opt"] }))
      .toEqual(["metrics.loss", "params.opt"]);
  });

  it("asks nothing for curves", () => {
    expect(jobChartKeys({ chart: "curves", x: "", y: "loss", color: "status", params: [] })).toEqual([]);
  });
});

describe("jobRows", () => {
  it("keeps each run's status and name next to its values", () => {
    const rows = jobRows(COLS);
    expect(rows[0]).toMatchObject({ verstr: "a", idx: 1, status: "succeeded", name: "t1", metrics: { loss: 0.5 }, params: { opt: "adam" } });
    expect(rows[2].metrics).toEqual({});
  });
});

describe("colorBy", () => {
  it("colours by status with the status tokens, in status order", () => {
    const g = colorBy(jobRows(COLS), "status");
    expect(g.colorOf.get("b")).toBe(STATUS_COLORS.failed);
    expect(g.colorOf.get("a")).toBe(STATUS_COLORS.succeeded);
    expect(g.legend.map((e) => e.label)).toEqual(["running", "failed", "succeeded", "waiting"]);
  });

  it("colours a param's values in their sorted order, missing ones as Other", () => {
    const g = colorBy(jobRows(COLS), "params.opt");
    expect(g.legend.map((e) => [e.label, e.count])).toEqual([["adam", 2], ["sgd", 1], ["Other", 1]]);
    expect(g.colorOf.get("a")).toBe(runColor(0));
    expect(g.colorOf.get("b")).toBe(runColor(1));
    expect(g.colorOf.get("d")).toBe(OTHER_COLOR);
  });

  it("folds values past the palette into Other, keeping the most common", () => {
    const n = PARAM_COLORS + 2;
    const verstrs = Array.from({ length: n * 2 }, (_, i) => `r${i}`);
    // v01..v07 twice each, v00 and v99 once: the rarest fold.
    const values = verstrs.map((_, i) => `v${String(Math.min(Math.floor(i / 2), n - 1)).padStart(2, "0")}`);
    values[0] = "v99";
    const cols: ExperimentColumns = { verstrs, idx: verstrs.map((_, i) => i), total: n * 2, columns: { "params.k": values } };
    const g = colorBy(jobRows(cols), "params.k");
    expect(g.legend).toHaveLength(PARAM_COLORS + 1);
    expect(g.legend[g.legend.length - 1].label).toBe("Other");
    expect(g.legend.map((e) => e.label)).not.toContain("v99");
  });
});

describe("boxGroups", () => {
  it("summarizes the metric per param value, values sorted, runs without either left out", () => {
    const boxes = boxGroups(jobRows(COLS), "params.opt", "loss");
    expect(boxes.groups.map((b) => [b.label, b.n, b.median])).toEqual([["adam", 1, 0.5], ["sgd", 1, 0.3]]);
    expect(boxes.dropped).toBe(0);
  });

  it("sorts numeric values numerically and computes quartiles", () => {
    const verstrs = ["a", "b", "c", "d", "e", "f"];
    const cols: ExperimentColumns = {
      verstrs, idx: [1, 2, 3, 4, 5, 6], total: 6,
      columns: { "params.bs": [128, 16, 16, 16, 16, 16], "metrics.loss": [1, 1, 2, 3, 4, 5] },
    };
    const [small, big] = boxGroups(jobRows(cols), "params.bs", "loss").groups;
    expect(small).toMatchObject({ label: "16", n: 5, min: 1, q1: 2, median: 3, q3: 4, max: 5 });
    expect(big.label).toBe("128");
  });

  it("keeps at most 20 groups, the most populated, and counts the rest as dropped", () => {
    const verstrs = Array.from({ length: 25 }, (_, i) => `r${i}`);
    const cols: ExperimentColumns = {
      verstrs, idx: verstrs.map((_, i) => i), total: 25,
      columns: { "params.k": verstrs.map((_, i) => i), "metrics.loss": verstrs.map(() => 1) },
    };
    const boxes = boxGroups(jobRows(cols), "params.k", "loss");
    expect(boxes.groups).toHaveLength(20);
    expect(boxes.dropped).toBe(5);
  });
});
