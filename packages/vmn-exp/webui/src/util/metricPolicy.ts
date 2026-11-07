/** Which summary policy picked a metric value (plan 32 F1): a run's own
 *  `define_metric` summary beats the schema's, so one column can mix them.
 *  The server lists those overrides on each row (`metric_policy`); a value
 *  without one follows the schema. */
import type { ExperimentRow, MetricPolicy, PolicyMix } from "../types";
import { plural } from "../util";

/** The override a cell names: its run's policy unlike the schema's; null
 *  when the run follows the schema or has no value. */
export function policyTag(r: ExperimentRow, m: string): MetricPolicy | null {
  return r.metrics[m] == null ? null : r.metric_policy?.[m] ?? null;
}

/** Whether a row of *rows* overrides the schema's policy for *m*. */
export const mixedPolicies = (rows: readonly ExperimentRow[], m: string): boolean =>
  rows.some((r) => policyTag(r, m) !== null);

/** `3 runs use min` per override of an aggregate's *policies*; null without one. */
export function mixText(policies: PolicyMix["policies"]): string | null {
  const parts = Object.entries(policies ?? {}).filter(([, n]) => n);
  if (!parts.length) return null;
  return parts.map(([p, n]) => `${plural(n!, "run")} ${n === 1 ? "uses" : "use"} ${p}`).join(", ");
}
