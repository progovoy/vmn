import type { SeriesPoint } from "../types";

export type StepRange = [number, number];

/** A step range fetched at full resolution, and its points. */
export interface Zoom {
  range: StepRange;
  points: SeriesPoint[];
}

const inRange = (p: SeriesPoint, [lo, hi]: StepRange) =>
  p.step !== null && p.step !== undefined && p.step >= lo && p.step <= hi;

/** *coarse* with its points inside the zoom's range swapped for the zoom's
 *  finer ones, so the rest of the curve stays drawn around them. */
export function spliceZoom(coarse: SeriesPoint[], zoom: Zoom | null): SeriesPoint[] {
  if (!zoom) return coarse;
  const [lo] = zoom.range;
  const outside = coarse.filter((p) => !inRange(p, zoom.range));
  const at = outside.findIndex((p) => p.step === null || p.step === undefined || p.step > lo);
  const cut = at < 0 ? outside.length : at;
  return [...outside.slice(0, cut), ...zoom.points, ...outside.slice(cut)];
}

/** Whether an x scale *range* covers the data's whole *extent* (a reset,
 *  not a zoom), with float slack. */
export function isFullRange(range: StepRange, extent: StepRange): boolean {
  const slack = Math.max(Math.abs(extent[1] - extent[0]), 1) * 1e-9;
  return range[0] <= extent[0] + slack && range[1] >= extent[1] - slack;
}
