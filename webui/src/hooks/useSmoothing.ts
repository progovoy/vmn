import { useMemo } from "react";

/** Exponential moving average.
 *  alpha=0 means no smoothing (returns original), alpha=0.99 means heavy smoothing.
 *  Formula: smoothed[i] = alpha * smoothed[i-1] + (1 - alpha) * data[i]
 */
export function ema(data: number[], alpha: number): number[] {
  if (data.length === 0) return [];
  const out: number[] = [data[0]];
  for (let i = 1; i < data.length; i++) {
    out.push(alpha * out[i - 1] + (1 - alpha) * data[i]);
  }
  return out;
}

export function useSmoothing(alpha: number): (data: number[]) => number[] {
  return useMemo(() => (data: number[]) => ema(data, alpha), [alpha]);
}
