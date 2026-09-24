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

/** *s* alone, or its raw curve (faded) under an EMA-smoothed copy. */
export function withSmoothing(s: CurveSeries, alpha: number): CurveSeries[] {
  if (alpha === 0) return [s];
  return [{ ...s, key: `${s.key}__raw`, faded: true }, { ...s, ys: emaXY(s.ys, alpha) }];
}

export function curveData(series: CurveSeries[]): uPlot.AlignedData {
  return [null, ...series.map((s) => [s.xs, s.ys])] as unknown as uPlot.AlignedData;
}

/** Width of the y axis, left of the plot area (the tooltip offsets by it). */
export const Y_AXIS_SIZE = 56;

export const X_TICK: Partial<Record<XMode, (v: number) => string>> = {
  wall: fmtWallTick,
  relative: fmtRelTick,
};

export interface CurveOptionsArgs {
  xMode: XMode;
  height: number;
  theme: ChartTheme;
  logY?: boolean;
  /** Hide the x axis (small multiples that only show a trend). */
  hideX?: boolean;
  read?: (name: string) => string;
}

/** An axis in the theme's colours (shared by the line and scatter charts). */
export function themedAxis(
  theme: ChartTheme, read?: (name: string) => string, extra: Partial<uPlot.Axis> = {}, grid = true,
): uPlot.Axis {
  return {
    stroke: theme.axis,
    grid: { show: grid, stroke: theme.grid, width: 1 },
    ticks: { stroke: theme.grid, width: 1 },
    font: `10.5px ${resolveCssColor("var(--mono, monospace)", read)}`,
    values: numAxisValues,
    ...extra,
  } as uPlot.Axis;
}

export function curveOptions(
  series: CurveSeries[], { xMode, height, theme, logY = false, hideX = false, read }: CurveOptionsArgs,
): Omit<uPlot.Options, "width"> {
  const axis = (extra: Partial<uPlot.Axis> = {}, grid = true) => themedAxis(theme, read, extra, grid);
  const xTick = X_TICK[xMode];
  return {
    mode: 2,
    height,
    legend: { show: false },
    focus: { alpha: 0.15 },
    cursor: { drag: { x: true, y: false, setScale: true }, points: { show: false } },
    scales: { x: { time: false }, y: { distr: logY ? 3 : 1 } },
    axes: [
      // Horizontal grid lines only, as the charts always had.
      axis({
        show: !hideX,
        ...(xTick ? { values: (_u: unknown, splits: number[]) => splits.map(xTick) } : {}),
      } as Partial<uPlot.Axis>, false),
      axis({ size: Y_AXIS_SIZE }),
    ],
    series: [
      {},
      ...series.map((s): uPlot.Series => ({
        label: s.label,
        stroke: resolveCssColor(s.color, read),
        width: s.faded ? 1 : 1.75,
        alpha: s.faded ? 0.35 : 1,
        points: { show: false },
      })),
    ],
  };
}
