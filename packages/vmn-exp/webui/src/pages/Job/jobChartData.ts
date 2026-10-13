/** The job Charts tab's data prep (plan 23 W4): the columns each chart asks
 *  `experiments-columns?scope=` for, rows from them, the colour-by groups
 *  (status tokens, or a param's values in the fixed categorical order) and
 *  the per-value boxes of a metric. */
import type { ExperimentColumns, ExperimentRow, RunState } from "../../types";
import { paramValue, runColor } from "../../util";
import type { ChartGroup, ChartGroups } from "../../util/chartGroups";
import { columnsToRows } from "../../util/chartColumns";
import { STATUS_ORDER } from "../../util/filterTokens";
import { isFiniteNumber } from "../../util/stats";

export const JOB_CHARTS = ["scatter", "parallel", "curves", "bypar"] as const;
export type JobChart = typeof JOB_CHARTS[number];

export interface JobChartAxes {
  chart: JobChart;
  /** A column key: `params.<k>` or `metrics.<k>` (bypar: the grouping param). */
  x: string;
  /** A metric name. */
  y: string;
  /** `status` or a column key. */
  color: string;
  /** The job's params (parallel coordinates draws each). */
  params: string[];
}

export type JobRow = ExperimentRow & { status?: RunState; name?: string | null };

/** The categorical slots a param's values get; the rest fold into Other. */
export const PARAM_COLORS = 6;
export const OTHER_COLOR = "var(--text-3)";
/** Most groups the box chart draws. */
export const MAX_BOXES = 20;

export const STATUS_COLORS: Record<RunState, string> = {
  running: "var(--st-running)", stuck: "var(--st-stuck)", failed: "var(--st-bad)",
  succeeded: "var(--st-good)", created: "var(--text-3)",
};
const STATUS_LABEL = (s: RunState) => (s === "created" ? "waiting" : s);

const uniq = (keys: string[]) => keys.filter((k, i) => k && keys.indexOf(k) === i);

/** The column keys *a.chart* plots. */
export function jobChartKeys(a: JobChartAxes): string[] {
  const y = `metrics.${a.y}`;
  switch (a.chart) {
    case "scatter": return uniq([a.x, y, a.color, "status", "name"]);
    case "parallel": return uniq([y, ...a.params.map((p) => `params.${p}`), a.color, "status", "name"]);
    case "bypar": return uniq([y, a.x]);
    case "curves": return [];
  }
}

/** One row per run, with its status and name when the columns carry them. */
export function jobRows(data: ExperimentColumns): JobRow[] {
  const status = data.columns.status, name = data.columns.name;
  return columnsToRows(data).map((r, i) => ({
    ...r,
    ...(status ? { status: status[i] as RunState } : {}),
    ...(name ? { name: (name[i] as string | null) ?? null } : {}),
  }));
}

/** A row's value of column *key* (`params.<k>`, `metrics.<k>` or `status`). */
export function columnValue(row: JobRow, key: string): unknown {
  if (key === "status") return row.status;
  if (key.startsWith("metrics.")) return row.metrics[key.slice(8)];
  if (key.startsWith("params.")) return paramValue(row, key.slice(7));
  return undefined;
}

const isMissing = (v: unknown) => v === null || v === undefined;

/** Values in display order: numbers numerically, then the rest as text. */
function compareValues(a: unknown, b: unknown): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "number") return -1;
  if (typeof b === "number") return 1;
  return String(a).localeCompare(String(b));
}

function countValues(rows: JobRow[], key: string): Map<string, { value: unknown; count: number }> {
  const counts = new Map<string, { value: unknown; count: number }>();
  for (const r of rows) {
    const v = columnValue(r, key);
    if (isMissing(v)) continue;
    const id = String(v);
    const c = counts.get(id);
    if (c) c.count++; else counts.set(id, { value: v, count: 1 });
  }
  return counts;
}

/** The *limit* most common values, in display order. */
function topValues(rows: JobRow[], key: string, limit: number) {
  const all = [...countValues(rows, key).values()];
  const kept = [...all].sort((a, b) => b.count - a.count || compareValues(a.value, b.value)).slice(0, limit);
  return { kept: kept.sort((a, b) => compareValues(a.value, b.value)), total: all.length };
}

function statusGroups(rows: JobRow[]): ChartGroups {
  const colorOf = new Map<string, string>();
  const count = new Map<RunState, number>();
  for (const r of rows) {
    if (!r.status) continue;
    colorOf.set(r.verstr, STATUS_COLORS[r.status] ?? OTHER_COLOR);
    count.set(r.status, (count.get(r.status) ?? 0) + 1);
  }
  const legend = STATUS_ORDER.filter((s) => count.has(s)).map((s): ChartGroup => ({
    key: s, label: STATUS_LABEL(s), color: STATUS_COLORS[s], count: count.get(s)!,
  }));
  return { colorOf, legend };
}

function paramGroups(rows: JobRow[], key: string): ChartGroups {
  const { kept } = topValues(rows, key, PARAM_COLORS);
  const colorByValue = new Map(kept.map((k, i) => [String(k.value), runColor(i)]));
  const colorOf = new Map<string, string>();
  for (const r of rows) {
    const v = columnValue(r, key);
    colorOf.set(r.verstr, (!isMissing(v) && colorByValue.get(String(v))) || OTHER_COLOR);
  }
  const legend: ChartGroup[] = kept.map((k) => ({
    key: String(k.value), label: String(k.value), color: colorByValue.get(String(k.value))!, count: k.count,
  }));
  const other = rows.length - kept.reduce((n, k) => n + k.count, 0);
  if (other > 0) legend.push({ key: "∅other", label: "Other", color: OTHER_COLOR, count: other });
  return { colorOf, legend };
}

/** Each run's colour and the legend naming them, by status or by column *key*. */
export function colorBy(rows: JobRow[], key: string): ChartGroups {
  return key === "status" ? statusGroups(rows) : paramGroups(rows, key);
}

export interface Box {
  label: string;
  n: number;
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
}

/** Linear-interpolated quantile *p* of sorted *xs*. */
function quantile(xs: number[], p: number): number {
  const pos = (xs.length - 1) * p;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo);
}

/** *metric* summarized per value of column *key*: at most MAX_BOXES groups
 *  (the most populated, in display order); `dropped` = the values left out. */
export function boxGroups(rows: JobRow[], key: string, metric: string): { groups: Box[]; dropped: number } {
  const withMetric = rows.filter((r) => isFiniteNumber(r.metrics[metric]));
  const { kept, total } = topValues(withMetric, key, MAX_BOXES);
  const byValue = new Map<string, number[]>(kept.map((k) => [String(k.value), []]));
  for (const r of withMetric) {
    const v = columnValue(r, key);
    if (!isMissing(v)) byValue.get(String(v))?.push(r.metrics[metric] as number);
  }
  const groups = kept.map((k) => {
    const xs = byValue.get(String(k.value))!.sort((a, b) => a - b);
    return {
      label: String(k.value), n: xs.length, min: xs[0], q1: quantile(xs, 0.25),
      median: quantile(xs, 0.5), q3: quantile(xs, 0.75), max: xs[xs.length - 1],
    };
  });
  return { groups, dropped: total - kept.length };
}
