/** Plan 20 C5: what the query help lists, from this app's facets and rows. */
import { describe, it, expect } from "vitest";
import { queryHelpData } from "../queryHelp";
import type { ExperimentRow } from "../../types";

const row = (i: number, extra: Partial<ExperimentRow> = {}): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null,
  branch: "main", base_version: "0.0.1", params: {}, metrics: {}, ...extra,
});
const ROWS = [
  row(1, { metrics: { val_loss: 0.52, acc: 0.8 }, params: { optimizer: "adam", lr: 0.01 }, tags: { team: "vision" } }),
  row(2, { metrics: { val_loss: 0.31, acc: 0.9 }, params: { optimizer: "sgd", lr: 0.1 } }),
  row(3, { metrics: { val_loss: 0.4467, acc: 0.85 }, params: { lr: 0.1 } }),
];
const FACETS = { metric_keys: ["val_loss", "acc"], param_keys: ["optimizer", "lr"] };

describe("queryHelpData", () => {
  it("lists the app's metric, param and tag keys as fields", () => {
    const help = queryHelpData({ facets: FACETS, branches: ["main"], rows: ROWS });
    expect(help.metrics).toEqual(["metrics.val_loss", "metrics.acc"]);
    expect(help.params).toEqual(["params.optimizer", "params.lr"]);
    expect(help.tags).toEqual(["tags.team"]);
  });

  it("builds three examples from real keys and values", () => {
    const help = queryHelpData({ facets: FACETS, branches: ["main", "feat/x"], rows: ROWS, schema: {} });
    expect(help.examples).toEqual([
      "metrics.val_loss < 0.45",
      'params.optimizer = "adam"',
      'status = "failed" and branch = "main"',
    ]);
  });

  it("compares the primary metric toward its goal", () => {
    const help = queryHelpData({ facets: FACETS, branches: [], rows: ROWS, primary: "acc" });
    expect(help.examples[0]).toBe("metrics.acc > 0.85");
    expect(help.examples[2]).toBe('status = "failed"');
  });

  it("fills in from tags and the note when the app has no metrics or params", () => {
    const rows = [row(1, { tags: { team: "vision" } })];
    const help = queryHelpData({ facets: {}, branches: [], rows });
    expect(help.examples).toEqual(['status = "failed"', 'tags.team = "vision"', 'note ~ "baseline"']);
  });
});
