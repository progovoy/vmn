/** Pure uPlot configuration for the line charts, kept apart from the
 *  component so it is testable without a canvas. Faceted mode (`mode: 2`)
 *  gives every curve its own x array: runs logged at different steps are
 *  never merged onto a shared, mostly-empty x axis. */
import type uPlot from "uplot";
import type { XMode } from "./chartData";
import { resolveCssColor, type ChartTheme } from "./cssColor";
import { emaXY, type XYSeries } from "./seriesArrays";

export interface CurveSeries extends XYSeries {
  key: string;
  label: string;
  color: string;
  /** Drawn thin and translucent (the raw curve under a smoothed one) and
   *  left out of the tooltip. */
  faded?: boolean;
}

export function fmtWallTick(ms: number): string {
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

export function fmtRelTick(secs: number): string {
  if (secs < 60) return `${Math.round(secs)}s`;
  if (secs < 3600) return `${Math.round(secs / 60)}m`;
  return `${Math.round(secs / 3600)}h`;
}

/** Decimals needed to write *step* exactly (0.25 -> 2, 50 -> 0). */
function stepDecimals(step: number): number {
  for (let d = 0; d < 15; d++) {
    const scaled = step * 10 ** d;
    if (Math.abs(scaled - Math.round(scaled)) < 1e-6) return d;
  }
  return 15;
}

/** Tick labels precise enough for *step*, so adjacent ticks never collide
 *  (uPlot's default keeps 3 decimals: 0.00495 and 0.005 both read "0.005"). */
export function fmtNumTicks(splits: number[], step: number): string[] {
  if (!(step > 0) || !Number.isFinite(step)) return splits.map(String);
  const maxAbs = Math.max(...splits.map(Math.abs));
  if (step < 1e-6 || maxAbs >= 1e6) {
    const digits = Math.max(0, Math.floor(Math.log10(maxAbs)) - Math.floor(Math.log10(step)));
    return splits.map((v) => (v === 0 ? "0" : v.toExponential(digits)));
  }
  const decimals = stepDecimals(step);
  return splits.map((v) => (Math.abs(v) < step / 2 ? 0 : v).toFixed(decimals));
}

const numAxisValues = (_u: unknown, splits: number[], _axis: number, _space: number, step: number) =>
  fmtNumTicks(splits, step);

/** One log-axis tick, compact and free of float noise: 0.001, 2e-4, 1e6. */
function fmtLogTick(v: number): string {
  const clean = Number(v.toPrecision(6));
  const abs = Math.abs(clean);
  if (abs >= 1e-3 && abs < 1e6) return String(clean);
  return clean.toExponential().replace("e+", "e");
}

/** Log-axis tick labels, each written from its own value: uPlot passes a
 *  log axis the linear increment of the whole range, so precision taken from
 *  it rounds the small ticks to "0". Splits uPlot filters out come as null. */
export function fmtLogTicks(splits: (number | null)[]): string[] {
  return splits.map((v) => (v == null ? "" : fmtLogTick(v)));
}

const logAxisValues = (_u: unknown, splits: (number | null)[]) => fmtLogTicks(splits);

/** *s* alone, or its raw curve (faded) under an EMA-smoothed copy. */
export function withSmoothing(s: CurveSeries, alpha: number): CurveSeries[] {
  if (alpha === 0) return [s];
  return [{ ...s, key: `${s.key}__raw`, faded: true }, { ...s, ys: emaXY(s.ys, alpha) }];
}

/** Below this spread relative to its value a chart is drawn flat. */
const FLAT_SPREAD = 1e-9;

export function curveData(series: CurveSeries[]): uPlot.AlignedData {
  const flat = flatValue(series.map((s) => s.ys));
  return [null, ...series.map((s) => [s.xs, flat === null ? s.ys : s.ys.map(() => flat)])] as unknown as uPlot.AlignedData;
}

/** The mean of a chart's values when they spread less than FLAT_SPREAD of
 *  it (values ~1 varying by 1e-10), else null. uPlot finds no usable y scale
 *  for such a chart and draws nothing, but pads a constant one; the wobble
 *  is invisible at any size, and the series (tooltips) keep their values. */
export function flatValue(columns: ArrayLike<number>[]): number | null {
  let min = Infinity, max = -Infinity, sum = 0, n = 0;
  for (const ys of columns) {
    for (let i = 0; i < ys.length; i++) {
      const y = ys[i];
      if (!Number.isFinite(y)) continue;
      if (y < min) min = y;
      if (y > max) max = y;
      sum += y;
      n++;
    }
  }
  if (!n || max === min) return null;
  const mean = sum / n;
  return max - min <= Math.abs(mean) * FLAT_SPREAD ? mean : null;
}

/** Narrowest y axis, left of the plot area (a tooltip with no measured plot
 *  edge offsets by it). */
export const Y_AXIS_SIZE = 56;
/** Axis label size. Whole pixels: uPlot scales the first /(\d+)px/ by the
 *  device pixel ratio, so "10.5px" would draw 5px labels on a 2x screen. */
const AXIS_FONT_PX = 11;
/** Advance of one AXIS_FONT_PX monospace glyph, and the tick + gap beside a label. */
const LABEL_CHAR_PX = 6.7;
const LABEL_PAD_PX = 16;

/** uPlot `size` of a y axis: as wide as its widest tick label (labels like
 *  1.792e+9 are not clipped), never narrower than Y_AXIS_SIZE. */
export function yAxisSize(_u: unknown, values: string[] | null): number {
  const widest = Math.max(0, ...(values ?? []).map((v) => String(v).length));
  return Math.max(Y_AXIS_SIZE, Math.ceil(widest * LABEL_CHAR_PX + LABEL_PAD_PX));
}

export const X_TICK: Partial<Record<XMode, (v: number) => string>> = {
  wall: fmtWallTick,
  relative: fmtRelTick,
};

export interface CurveOptionsArgs {
  xMode: XMode;
  height: number;
  theme: ChartTheme;
  logY?: boolean;
  read?: (name: string) => string;
}

/** Most ticks one axis gets from :func:`safeSplits`. */
const MAX_TICKS = 100;

/** A linear axis's ticks: every multiple of *incr* in [min, max], each
 *  computed as start + i * incr and capped at MAX_TICKS, so it always ends.
 *  uPlot's own loop (val = roundDec(val + incr)) stops advancing on a
 *  near-flat axis, e.g. values ~1 varying by 1e-10, and never ends
 *  (RangeError "Invalid array length"). */
export function safeSplits(_u: unknown, _axis: number, min: number, max: number, incr: number): number[] {
  if (!(incr > 0) || !Number.isFinite(min) || !Number.isFinite(max) || max < min) return [min];
  const start = Math.ceil(min / incr) * incr;
  const n = Math.min(Math.floor((max - start) / incr + 1e-9), MAX_TICKS);
  const out: number[] = [];
  for (let i = 0; i <= n; i++) {
    const v = Number((start + i * incr).toPrecision(12));
    if (out[out.length - 1] !== v) out.push(Object.is(v, -0) ? 0 : v);
  }
  return out.length ? out : [min];
}

/** An axis in the theme's colours (shared by the line and scatter charts). */
export function themedAxis(
  theme: ChartTheme, read?: (name: string) => string, extra: Partial<uPlot.Axis> = {}, grid = true,
): uPlot.Axis {
  return {
    stroke: theme.axis,
    grid: { show: grid, stroke: theme.grid, width: 1 },
    ticks: { stroke: theme.grid, width: 1 },
    font: `${AXIS_FONT_PX}px ${resolveCssColor("var(--mono, monospace)", read)}`,
    values: numAxisValues,
    splits: safeSplits,
    ...extra,
  } as uPlot.Axis;
}

/** The x scale's range: uPlot's own, but a zero-wide one (every point at
 *  one x, or a single point) is widened, since uPlot's tick loop never ends
 *  on it (RangeError "Invalid array length"). */
export function xRange(_u: unknown, min: number, max: number): uPlot.Range.MinMax {
  if (min !== max) return [min, max];
  const pad = Math.abs(min) * 0.1 || 1;
  return [min - pad, max + pad];
}

export function curveOptions(
  series: CurveSeries[], { xMode, height, theme, logY = false, read }: CurveOptionsArgs,
): Omit<uPlot.Options, "width"> {
  const axis = (extra: Partial<uPlot.Axis> = {}, grid = true) => themedAxis(theme, read, extra, grid);
  const xTick = X_TICK[xMode];
  return {
    mode: 2,
    height,
    legend: { show: false },
    focus: { alpha: 0.15 },
    cursor: { drag: { x: true, y: false, setScale: true }, points: { show: false } },
    scales: { x: { time: false, range: xRange }, y: { distr: logY ? 3 : 1 } },
    axes: [
      // Horizontal grid lines only, as the charts always had.
      axis({
        ...(xTick ? { values: (_u: unknown, splits: number[]) => splits.map(xTick) } : {}),
      } as Partial<uPlot.Axis>, false),
      // A log axis keeps uPlot's own (log) ticks.
      axis({ size: yAxisSize, ...(logY ? { values: logAxisValues, splits: undefined } : {}) } as Partial<uPlot.Axis>),
    ],
    series: [
      {},
      ...series.map((s): uPlot.Series => ({
        label: s.label,
        stroke: resolveCssColor(s.color, read),
        width: s.faded ? 1 : 1.75,
        alpha: s.faded ? 0.35 : 1,
        // A metric logged once is one point: no line, so draw the dot.
        points: { show: s.xs.length === 1 },
      })),
    ],
  };
}
