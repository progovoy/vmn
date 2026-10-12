import type { ExperimentDetail } from "../types";

/** True when *key* is a parameter (present in `params`) and was never logged
 *  as a metric more than once (no `metric_summary` entry). Numeric params
 *  fold into the `metrics` dict on list rows, but they belong in the params
 *  card, not the metrics card. */
export function isParamOnly(key: string, detail: ExperimentDetail): boolean {
  if (!detail.params || !(key in detail.params)) return false;
  if (detail.metric_summary && key in detail.metric_summary) return false;
  return true;
}
