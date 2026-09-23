import { useMemo } from "react";

/** Exponential moving average.
 *  alpha=0 means no smoothing (returns original), alpha=0.99 means heavy smoothing.
 *  Formula: smoothed[i] = alpha * smoothed[i-1] + (1 - alpha) * data[i]
 *
 *  Gaps (null / undefined / NaN — a metric logged at a sparser cadence than
 *  its neighbours) stay gaps in the output and are skipped by the running
 *  average, so one missing point never turns the rest of the curve into NaN.
 */
export function ema(data: readonly (number | null | undefined)[], alpha: number): number[] {
  const out: number[] = [];
  let prev: number | undefined;
  for (const v of data) {
    if (typeof v !== "number" || Number.isNaN(v)) {
      out.push(undefined as unknown as number);
      continue;
    }
    prev = prev === undefined ? v : alpha * prev + (1 - alpha) * v;
    out.push(prev);
  }
  return out;
}

export function useSmoothing(alpha: number): (data: number[]) => number[] {
  return useMemo(() => (data: number[]) => ema(data, alpha), [alpha]);
}
