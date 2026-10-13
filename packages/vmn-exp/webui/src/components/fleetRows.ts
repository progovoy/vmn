/** The fleet/sweep table's rows (plan 20 B6): a child's label, the params
 *  that vary among the children, its goal-metric value and progress, and
 *  how the table sorts them. Pure. */
import type { Fleet, FleetChild, MetricsSchema, RunState } from "../types";
import { metricGoal } from "../util";

export type Goal = "min" | "max" | null;

export interface FleetRow {
  verstr: string;
  /** `@N name`, see {@link fleetLabel}. */
  label: string;
  status: RunState | null;
  params: Record<string, unknown>;
  /** The table metric's value; null when the run has none. */
  value: number | null;
  /** The run the value came from, when not this one (a sweep's nested run). */
  valueFrom?: string;
  progress: { step: number; of: number } | null;
  trial?: number;
  stoppedEarly?: boolean;
}

export type SortKey = "trial" | "label" | "status" | "value" | "progress" | `p:${string}`;
export type Order = "asc" | "desc";

/** `@N name`, `@N`, the name, else the verstr. */
export function fleetLabel(r: { verstr: string; idx?: number | null; name?: string | null }): string {
  if (r.idx != null) return r.name ? `@${r.idx} ${r.name}` : `@${r.idx}`;
  return r.name || r.verstr;
}

const isNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** `last_step / of` when the total is known, else the logged progress. */
export function childProgress(c: FleetChild): FleetRow["progress"] {
  const s = c.last_step;
  if (s && isNumber(s.step) && isNumber(s.of)) return { step: s.step, of: s.of };
  if (isNumber(c.progress) && isNumber(c.progress_total)) return { step: c.progress, of: c.progress_total };
  return null;
}

/** The metric the fleet table shows: the schema's primary one, else the first
 *  child metric with a goal (D1) — never a param folded into `metrics` (D2). */
export function fleetMetric(children: FleetChild[], schema: MetricsSchema | null): { name: string; goal: Goal } | null {
  const keys = new Set<string>();
  for (const c of children) {
    for (const k of Object.keys(c.metrics ?? {})) if (!(k in (c.params ?? {}))) keys.add(k);
  }
  const names = [...keys].sort();
  const primary = names.find((k) => schema?.[k]?.primary);
  const name = primary ?? names.find((k) => metricGoal(schema, k) !== null);
  return name ? { name, goal: metricGoal(schema, name) } : null;
}

export function fleetRowsOf(children: FleetChild[], metric: { name: string; goal?: Goal } | null): FleetRow[] {
  return children.map((c) => {
    const v = metric ? c.metrics?.[metric.name] : null;
    return {
      verstr: c.verstr, label: fleetLabel(c), status: c.status, params: c.params ?? {},
      value: isNumber(v) ? v : null, progress: childProgress(c),
    };
  });
}

const MAX_PARAMS = 6;
const shown = (v: unknown) => (v === undefined ? "\u0000missing" : JSON.stringify(v));

/** Params whose values differ among *rows* (missing counts as a value),
 *  *preferred* ones first, at most six. */
export function varyingParams(rows: FleetRow[], preferred: string[] = []): string[] {
  const all = new Set(rows.flatMap((r) => Object.keys(r.params)));
  const ordered = [...preferred.filter((k) => all.has(k)), ...[...all].filter((k) => !preferred.includes(k)).sort()];
  return ordered
    .filter((k) => new Set(rows.map((r) => shown(r.params[k]))).size > 1)
    .slice(0, MAX_PARAMS);
}

function sortValue(r: FleetRow, key: SortKey): number | string | null {
  if (key === "value") return r.value;
  if (key === "trial") return r.trial ?? null;
  if (key === "label") return r.label;
  if (key === "status") return r.status;
  if (key === "progress") return r.progress ? r.progress.step / r.progress.of : null;
  const v = r.params[key.slice(2)];
  return typeof v === "number" || typeof v === "string" ? v : v == null ? null : JSON.stringify(v);
}

function compare(a: number | string, b: number | string): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true });
}

/** *rows* sorted on *key*; missing values last in both directions. */
export function sortRows(rows: FleetRow[], key: SortKey, order: Order): FleetRow[] {
  const sign = order === "asc" ? 1 : -1;
  return [...rows].sort((x, y) => {
    const a = sortValue(x, key), b = sortValue(y, key);
    if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
    return sign * compare(a, b);
  });
}

/** The verstr of the best value toward *goal*; none without a goal (D1). */
export function bestOf(rows: FleetRow[], goal: Goal): string | null {
  if (!goal) return null;
  const scored = rows.filter((r) => r.value !== null);
  if (scored.length === 0) return null;
  return sortRows(scored, "value", goal === "min" ? "asc" : "desc")[0].verstr;
}

/** A header's first direction: a metric toward its goal (high first without
 *  one), anything else ascending. */
export const firstOrder = (key: SortKey, goal: Goal): Order =>
  key === "value" ? (goal === "min" ? "asc" : "desc") : "asc";

/** A child's `@N` from the outer run's *fleet* (which details its first 50). */
export function fleetIdxOf(fleet: Fleet | null | undefined): (verstr: string) => number | null {
  const idx = new Map((fleet?.children ?? []).map((c) => [c.verstr, c.idx ?? null]));
  return (verstr) => idx.get(verstr) ?? null;
}
