/** A param's value as compared across runs (objects by their JSON). */
const shown = (v: unknown) => (v !== null && typeof v === "object" ? JSON.stringify(v) : String(v));

/** *params* with the keys whose values differ among *rows* (a run lacking
 *  the key counts as differing) first, each group in its own order. The
 *  same object when nothing varies, so the card keeps its identity. */
export function paramsVariedFirst<P extends Record<string, unknown> | null | undefined>(
  params: P, rows: { params?: Record<string, unknown> | null }[],
): P {
  if (!params || rows.length < 2) return params;
  const varies = (k: string) => new Set(rows.map((r) => (r.params && k in r.params ? shown(r.params[k]) : "\u0000"))).size > 1;
  const keys = Object.keys(params);
  const varied = keys.filter(varies);
  if (varied.length === 0 || varied.length === keys.length) return params;
  const rest = keys.filter((k) => !varied.includes(k));
  return Object.fromEntries([...varied, ...rest].map((k) => [k, params[k]])) as P;
}
