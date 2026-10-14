/** Parallel-coordinates brushes as a query clause (plan 23 W4), so "show the
 *  brushed runs" opens the Runs tab filtered to exactly them. Each brushed
 *  axis is bounded by the values of the runs inside its brush, so the clause
 *  never drifts from the picture by a rounding of the axis scale. The query
 *  language has no escapes: text holding both quotes gives no clause. */
import type { ExperimentRow } from "../types";
import { axisT, rawValue, type Axis, type Brushes } from "./parallelData";
import { literal } from "./queryHelp";
import { quoteLiteral } from "./searchQuery";
import { maxOf, minOf } from "./stats";

/** `metrics.<name>` / `params.<name>` / `tags.<name>`, quoted when the name is no plain identifier. */
export function fieldPath(group: "metrics" | "params" | "tags", name: string): string | null {
  if (/^\w+$/.test(name)) return `${group}.${name}`;
  const quoted = quoteLiteral(name);
  return quoted && `${group}.${quoted}`;
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

function axisClause(axis: Axis, values: unknown[], field: string): string | null {
  if (axis.kind === "num") return `${field} >= ${minOf(values)} and ${field} <= ${maxOf(values)}`;
  const literals = [...new Set(values)].map(literal);
  return literals.every((l) => l !== null) ? `${field} in (${literals.join(", ")})` : null;
}

/** The brushes as one ANDed clause; null with no brush, when one holds no
 *  run, or when a name or value can't be written as a literal. */
export function brushQuery(
  rows: ExperimentRow[], axes: Axis[], metricCols: string[], brushes: Brushes,
): string | null {
  const metrics = new Set(metricCols);
  const clauses: string[] = [];
  for (const [d, [a, b]] of [...brushes].sort((x, y) => x[0] - y[0])) {
    const axis = axes[d];
    if (!axis) continue;
    const values = brushedValues(rows, axis, metricCols, Math.min(a, b), Math.max(a, b));
    const field = fieldPath(metrics.has(axis.name) ? "metrics" : "params", axis.name);
    const clause = values.length && field ? axisClause(axis, values, field) : null;
    if (!clause) return null;
    clauses.push(clause);
  }
  return clauses.length ? clauses.join(" and ") : null;
}
