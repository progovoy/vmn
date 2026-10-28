import type uPlot from "uplot";
import type { RunRange } from "../types";

/** A uPlot `draw` hook that strokes a dashed vertical line at x = *step* —
 *  the step a forked run branched off its source. Off-screen steps (zoomed
 *  away) draw nothing. */
export function stepMarkerHook(step: number, color: string) {
  return (u: uPlot) => {
    const { min, max } = u.scales.x ?? {};
    if (min == null || max == null || step < min || step > max) return;
    const x = u.valToPos(step, "x", true);
    const { ctx, bbox } = u;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(x, bbox.top);
    ctx.lineTo(x, bbox.top + bbox.height);
    ctx.stroke();
    ctx.restore();
  };
}

/** *options* with a step marker drawn on top, or unchanged without one. */
export function withStepMarker<T extends Omit<uPlot.Options, "width">>(
  options: T, step: number | null | undefined, color: string,
): T {
  if (step == null) return options;
  const draw = [...(options.hooks?.draw ?? []), stepMarkerHook(step, color)];
  return { ...options, hooks: { ...options.hooks, draw } };
}

/** How opaque a range band is over the plot background. */
const BAND_ALPHA = 0.12;

/** A uPlot `drawClear` hook (under the curves) that shades each of *ranges*
 *  (`run.mark_range`) as an x band, clipped to the visible x range. */
export function rangeBandsHook(ranges: RunRange[], color: string) {
  return (u: uPlot) => {
    const { min, max } = u.scales.x ?? {};
    if (min == null || max == null) return;
    const { ctx, bbox } = u;
    ctx.save();
    ctx.fillStyle = color;
    ctx.globalAlpha = BAND_ALPHA;
    for (const r of ranges) {
      if (r.end_step < min || r.start_step > max) continue;
      const left = u.valToPos(Math.max(r.start_step, min), "x", true);
      const right = u.valToPos(Math.min(r.end_step, max), "x", true);
      ctx.fillRect(left, bbox.top, Math.max(right - left, 1), bbox.height);
    }
    ctx.restore();
  };
}

/** *options* with *ranges* shaded under the curves, or unchanged without any. */
export function withRangeBands<T extends Omit<uPlot.Options, "width">>(
  options: T, ranges: RunRange[] | null | undefined, color: string,
): T {
  if (!ranges?.length) return options;
  const drawClear = [...(options.hooks?.drawClear ?? []), rangeBandsHook(ranges, color)];
  return { ...options, hooks: { ...options.hooks, drawClear } };
}
