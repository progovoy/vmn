import { memo, useEffect, useRef } from "react";
import { yFromT } from "../util/parallelData";
import { resolveCssColor } from "../util/cssColor";

export interface PlotGeometry {
  matrix: Float64Array;
  nDims: number;
  xs: number[];
  top: number;
  plotH: number;
  w: number;
  h: number;
  /** One stroke colour per row (few distinct values: the scale is quantized). */
  strokes: string[];
  selected: Set<number> | null;
}

/** Row indices grouped by stroke, so each colour is one path and one stroke(). */
function groupByStroke(rows: number[], strokes: string[]): Map<string, number[]> {
  const groups = new Map<string, number[]>();
  for (const r of rows) {
    const g = groups.get(strokes[r]);
    if (g) g.push(r); else groups.set(strokes[r], [r]);
  }
  return groups;
}

type Ctx = CanvasRenderingContext2D;

function tracePolylines(ctx: Ctx, rows: number[], g: PlotGeometry, dpr: number) {
  const { matrix, nDims, xs, top, plotH } = g;
  for (const r of rows) {
    let on = false;
    for (let d = 0; d < nDims; d++) {
      const t = matrix[r * nDims + d];
      if (Number.isNaN(t)) { on = false; continue; }
      const x = xs[d] * dpr, y = yFromT(t, top, plotH) * dpr;
      if (on) ctx.lineTo(x, y); else { ctx.moveTo(x, y); on = true; }
    }
  }
}

function strokeGroup(ctx: Ctx, color: string, alpha: number, dpr: number, trace: () => void) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.globalAlpha = alpha;
  ctx.lineWidth = dpr;
  ctx.beginPath();
  trace();
  ctx.stroke();
  ctx.restore();
}

function draw(ctx: Ctx, g: PlotGeometry, dpr: number) {
  const { xs, top, plotH, w, h, strokes, selected } = g;
  ctx.clearRect(0, 0, w * dpr, h * dpr);
  const all = strokes.map((_, i) => i);
  const active = selected ? all.filter((i) => selected.has(i)) : all;
  if (selected) {
    const faded = all.filter((i) => !selected.has(i));
    strokeGroup(ctx, resolveCssColor("var(--text-3)", undefined, "gray"), 0.06, dpr,
      () => tracePolylines(ctx, faded, g, dpr));
  }
  for (const [color, rows] of groupByStroke(active, strokes)) {
    strokeGroup(ctx, resolveCssColor(color, undefined, "gray"), 0.45, dpr,
      () => tracePolylines(ctx, rows, g, dpr));
  }
  strokeGroup(ctx, resolveCssColor("var(--line-2)", undefined, "gray"), 1, dpr, () => {
    for (const x of xs) {
      ctx.moveTo(x * dpr, top * dpr);
      ctx.lineTo(x * dpr, (top + plotH) * dpr);
    }
  });
}

/** Canvas renderer for large row counts, drawn at devicePixelRatio. */
function ParallelCanvas({ matrix, nDims, xs, top, plotH, w, h, strokes, selected }: PlotGeometry) {
  const ref = useRef<HTMLCanvasElement>(null);
  const dpr = window.devicePixelRatio || 1;
  useEffect(() => {
    const ctx = ref.current?.getContext("2d");
    if (ctx) draw(ctx, { matrix, nDims, xs, top, plotH, w, h, strokes, selected }, dpr);
  }, [matrix, nDims, xs, top, plotH, w, h, strokes, selected, dpr]);
  return (
    <canvas ref={ref} width={w * dpr} height={h * dpr}
      style={{ display: "block", width: `${w}px`, height: `${h}px` }} />
  );
}

export default memo(ParallelCanvas);
