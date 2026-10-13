/** Parallel-coordinates brushes as a query clause (plan 23 W4), so "show the
 *  brushed runs" opens the Runs tab filtered to exactly them. Each brushed
 *  axis is bounded by the values of the runs inside its brush, so the clause
 *  never drifts from the picture by a rounding of the axis scale. */
import type { ExperimentRow } from "../types";
import { axisT, rawValue, type Axis, type Brushes } from "./parallelData";
import { quoteLiteral } from "./searchQuery";

const asString = (text: string) => quoteLiteral(text) ?? JSON.stringify(text);

/** `metrics.<name>` / `params.<name>`, quoted when the name is no plain identifier. */
export function fieldPath(group: "metrics" | "params", name: string): string {
  return /^\w+$/.test(name) ? `${group}.${name}` : `${group}.${asString(name)}`;
}

function literal(v: unknown): string {
  return typeof v === "number" || typeof v === "boolean" ? String(v) : asString(String(v));
}

/** The raw values of the rows whose t on *axis* lies within [lo, hi]. */
function brushedValues(rows: ExperimentRow[], axis: Axis, metricCols: string[], lo: number, hi: number) {
  const out: unknown[] = [];
  for (const r of rows) {
    const v = rawValue(r, axis.name, metricCols);
    const t = axisT(axis, v);
    if (t !== null && t >= lo && t <= hi) out.push(v);
  }
  return out;
}

function axisClause(axis: Axis, values: unknown[], field: string): string {
  if (axis.kind === "cat") return `${field} in (${[...new Set(values)].map(literal).join(", ")})`;
  let lo = Infinity, hi = -Infinity;
  for (const v of values as number[]) { if (v < lo) lo = v; if (v > hi) hi = v; }
  return `${field} >= ${lo} and ${field} <= ${hi}`;
}

/** The brushes as one ANDed clause; null with no brush or when one holds no run. */
export function brushQuery(
  rows: ExperimentRow[], axes: Axis[], metricCols: string[], brushes: Brushes,
): string | null {
  const metrics = new Set(metricCols);
  const clauses: string[] = [];
  for (const [d, [a, b]] of [...brushes].sort((x, y) => x[0] - y[0])) {
    const axis = axes[d];
    if (!axis) continue;
    const values = brushedValues(rows, axis, metricCols, Math.min(a, b), Math.max(a, b));
    if (!values.length) return null;
    clauses.push(axisClause(axis, values, fieldPath(metrics.has(axis.name) ? "metrics" : "params", axis.name)));
  }
  return clauses.length ? clauses.join(" and ") : null;
}
