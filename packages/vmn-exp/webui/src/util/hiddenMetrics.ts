/** Metrics the schema marks `hidden` — kept out of the leaderboard's default
 *  columns (the server's `/metrics-schema` merges conf.yml with what runs
 *  declare). Keys are exact names or fnmatch globs; the exact name wins,
 *  else the last matching glob, like the server's `step_metric.lookup`. */
import type { MetricsSchema } from "../types";
import { globRegExp } from "./metricGlob";

/** Whether *schema* hides metric *name*. */
export function schemaHides(schema: MetricsSchema | null, name: string): boolean {
  if (!schema) return false;
  const exact = schema[name]?.hidden;
  if (typeof exact === "boolean") return exact;
  const patterns = Object.keys(schema).reverse();
  for (const pattern of patterns) {
    const hidden = schema[pattern].hidden;
    if (typeof hidden === "boolean" && globRegExp(pattern).test(name)) return hidden;
  }
  return false;
}
