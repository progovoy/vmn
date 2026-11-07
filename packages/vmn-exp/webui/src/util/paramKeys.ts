import type { ExperimentDetail } from "../types";

/** What tells a folded param from a logged metric: a row or a run detail. */
export interface ParamFoldSource {
  params?: Record<string, unknown>;
  logged_params?: readonly string[];
}

/** True when *key*'s `metrics` value is a numeric param's fold: *key* is a
 *  param the run never logged as a metric (`logged_params`, plan 32 F8). */
export function isFoldedParam(source: ParamFoldSource, key: string): boolean {
  return Boolean(source.params && key in source.params) && !source.logged_params?.includes(key);
}

/** True when *key* belongs in the run's params card, not its metrics card. */
export function isParamOnly(key: string, detail: ExperimentDetail): boolean {
  return isFoldedParam(detail, key);
}
