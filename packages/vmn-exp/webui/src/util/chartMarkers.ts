import type uPlot from "uplot";

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
