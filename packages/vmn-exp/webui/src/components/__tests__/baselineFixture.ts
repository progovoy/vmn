/** An outer run's baseline comparison as `experiments/{v}/baseline` serves it (plan 28 N3). */
import type { BaselineChipData, BaselineCompare, BaselineRef } from "../../apiBaseline";

export const CHIP: BaselineChipData = {
  state: "worse", text: "▼ best_value from 2024-12 (5 of 41 trade_date values worse than the baseline's p10)",
  metric: "best_value", from: "2024-12", worse: 5, of: 41, quantile: "p10", threshold: 0.9,
};

export const REF: BaselineRef = {
  verstr: "0.0.1-dev.base", idx: 12, name: "wf_41aa", status: "succeeded", source: "latest",
  started_at: null, finished_at: null,
};

const d = (value: number | null, baseline: number | null, delta: number | null, better: boolean | null) =>
  ({ value, baseline, delta, better });

export function compareFixture(over: Partial<BaselineCompare> = {}): BaselineCompare {
  return {
    verstr: "0.0.2-rc.1", match: ["params.table_name", "params.model_type"], by: "params.trade_date",
    values: { "params.table_name": "t1", "params.model_type": "m1" },
    baseline: REF, metric: "best_value", goal: "max",
    metrics: { best_value: { best: d(1.21, 1.3, -0.09, false), median: d(0.9, 0.8, 0.1, true) } },
    failed_pct: d(5, 2, 3, false), duration_p90: d(7200, 3600, 3600, false),
    attention: [{ key: "unstable", label: "unstable", level: "warn", q: 'tags.health = "unstable"',
      count: 12, baseline_count: 3, ...d(0.12, 0.03, 0.09, false) }],
    own: { cost_per_date: d(5, 4, 1, null) },
    pairs: [
      { key: "2024-06", label: "2024-06", verstr: "c1", idx: 101, baseline_verstr: "b1", done: true, worse: false, ...d(1.1, 1.0, 0.1, true) },
      { key: "2024-12", label: "2024-12", verstr: "c2", idx: 102, baseline_verstr: "b2", done: true, worse: true, ...d(0.2, 1.0, -0.8, false) },
      { key: "2025-06", label: "2025-06", verstr: "c3", idx: 103, baseline_verstr: "b3", done: false, ...d(null, 1.0, null, null) },
    ],
    pairs_total: 4,
    chip: CHIP,
    ...over,
  };
}
