/** Loop-based reductions: `Math.min(...arr)` throws RangeError once an array
 *  outgrows the engine's argument limit (~65k in Safari, ~120k in V8). */

/** Whether *v* is a real, finite number (the server serializes NaN/inf as null). */
export function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** *v* when it is a finite number, else null. */
export function finiteOrNull(v: unknown): number | null {
  return isFiniteNumber(v) ? v : null;
}

export function finiteNumbers(values: readonly unknown[]): number[] {
  const out: number[] = [];
  for (const v of values) {
    if (isFiniteNumber(v)) out.push(v);
  }
  return out;
}

/** Smallest finite number in *values*, or NaN when there is none. */
export function minOf(values: readonly unknown[]): number {
  let best = NaN;
  for (const v of values) {
    if (isFiniteNumber(v) && !(v >= best)) best = v;
  }
  return best;
}

/** Largest finite number in *values*, or NaN when there is none. */
export function maxOf(values: readonly unknown[]): number {
  let best = NaN;
  for (const v of values) {
    if (isFiniteNumber(v) && !(v <= best)) best = v;
  }
  return best;
}
