/** Loop-based reductions: `Math.min(...arr)` throws RangeError once an array
 *  outgrows the engine's argument limit (~65k in Safari, ~120k in V8). */

export function finiteNumbers(values: readonly unknown[]): number[] {
  const out: number[] = [];
  for (const v of values) {
    if (typeof v === "number" && Number.isFinite(v)) out.push(v);
  }
  return out;
}

/** Smallest finite number in *values*, or NaN when there is none. */
export function minOf(values: readonly unknown[]): number {
  let best = NaN;
  for (const v of values) {
    if (typeof v === "number" && Number.isFinite(v) && !(v >= best)) best = v;
  }
  return best;
}

/** Largest finite number in *values*, or NaN when there is none. */
export function maxOf(values: readonly unknown[]): number {
  let best = NaN;
  for (const v of values) {
    if (typeof v === "number" && Number.isFinite(v) && !(v <= best)) best = v;
  }
  return best;
}
