/** Metrics the schema marks `hidden` — kept out of the leaderboard's default
 *  columns (the server's `/metrics-schema` merges conf.yml with what runs
 *  declare). Keys are exact names or fnmatch globs; the exact name wins,
 *  else the last matching glob, like the server's `step_metric.lookup`. */
import type { MetricsSchema } from "../types";

const globCache = new Map<string, RegExp>();

/** fnmatch's `*`, `?` and `[...]` (`[!...]` negates); all else literal. */
function globRegExp(pattern: string): RegExp {
  let re = globCache.get(pattern);
  if (re) return re;
  let src = "";
  for (let i = 0; i < pattern.length; i++) {
    const c = pattern[i];
    const close = c === "[" ? pattern.indexOf("]", i + 2) : -1;
    if (c === "*") src += ".*";
    else if (c === "?") src += ".";
    else if (close > 0) {
      const body = pattern.slice(i + 1, close).replace(/\\/g, "\\\\");
      src += body.startsWith("!") ? `[^${body.slice(1)}]` : `[${body}]`;
      i = close;
    } else src += c.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  re = new RegExp(`^${src}$`, "s");
  globCache.set(pattern, re);
  return re;
}

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
