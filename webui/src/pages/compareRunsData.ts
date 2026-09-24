/** Pure logic behind the N-run compare table. */
import type { ExperimentDetail, MetricsSchema } from "../types";
import { metricGoal } from "../util";
import { finiteNumbers, maxOf, minOf } from "../util/stats";
import { setAllParams } from "../hooks/useUrlState";
import { summaryFromDetail } from "./runSummary";

export const MAX_COMPARE_RUNS = 50;

/** The `sel` verstrs in order, deduped and capped at MAX_COMPARE_RUNS. */
export function parseSelection(params: URLSearchParams): { verstrs: string[]; dropped: number } {
  const unique = [...new Set(params.getAll("sel").filter(Boolean))];
  return {
    verstrs: unique.slice(0, MAX_COMPARE_RUNS),
    dropped: Math.max(0, unique.length - MAX_COMPARE_RUNS),
  };
}

/** *params* minus one selected run, everything else kept. */
export function withoutRun(params: URLSearchParams, verstr: string): URLSearchParams {
  const next = new URLSearchParams(params);
  setAllParams(next, "sel", next.getAll("sel").filter((v) => v !== verstr));
  return next;
}

/** A run's display name: its `name`, else its verstr. */
export function runLabel(verstr: string, detail: ExperimentDetail | undefined): string {
  const name = detail?.metadata.name;
  return typeof name === "string" && name ? name : verstr;
}

export interface CompareRow {
  key: string;
  /** One per run, `undefined` where the run lacks the key (or hasn't loaded). */
  values: unknown[];
  /** The loaded runs disagree (a missing value counts as a value). */
  differs: boolean;
  /** Best numeric value of a metric row; null when there is nothing to beat. */
  best: number | null;
}

const sourceOf = (d: ExperimentDetail, kind: "params" | "metrics") =>
  (kind === "params" ? summaryFromDetail(d).params : d.metrics) ?? {};

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

function bestOf(values: unknown[], goal: "min" | "max"): number | null {
  const nums = finiteNumbers(values);
  if (nums.length < 2) return null;
  const lo = minOf(nums);
  const hi = maxOf(nums);
  if (lo === hi) return null;
  return goal === "min" ? lo : hi;
}

/** One row per key across the runs' params or metrics, keys sorted. */
export function compareRows(
  runs: (ExperimentDetail | undefined)[], kind: "params" | "metrics", schema: MetricsSchema | null,
): CompareRow[] {
  const sources = runs.map((d) => (d ? sourceOf(d, kind) : undefined));
  const keys = new Set<string>();
  sources.forEach((s) => s && Object.keys(s).forEach((k) => keys.add(k)));
  return [...keys].sort().map((key) => {
    const values = sources.map((s) => s?.[key]);
    const loaded = values.filter((_, i) => sources[i] !== undefined);
    return {
      key,
      values,
      differs: loaded.some((v) => !same(v, loaded[0])),
      best: kind === "metrics" ? bestOf(values, metricGoal(schema, key)) : null,
    };
  });
}
