/** Loop-based min/max. Spreading a large array into Math.min/Math.max throws
 *  RangeError past ~100k arguments, so never do that on per-run data.
 *  Null and non-finite values are skipped; an empty input gives NaN. */
export function minOf(xs: readonly (number | null | undefined)[]): number {
  let out = NaN;
  for (const x of xs) {
    if (typeof x === "number" && Number.isFinite(x) && !(x >= out)) out = x;
  }
  return out;
}

export function maxOf(xs: readonly (number | null | undefined)[]): number {
  let out = NaN;
  for (const x of xs) {
    if (typeof x === "number" && Number.isFinite(x) && !(x <= out)) out = x;
  }
  return out;
}
