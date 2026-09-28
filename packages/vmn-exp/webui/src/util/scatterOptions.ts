/** Pure uPlot configuration for the metric scatter: points only, one series
 *  per point group, each with its own x/y arrays (faceted mode). */
import type uPlot from "uplot";
import { resolveCssColor, type ChartTheme } from "./cssColor";
import { themedAxis, Y_AXIS_SIZE } from "./curveOptions";
import type { PointGroup } from "./scatterData";

/** Past this many points they are drawn smaller, so dense clouds stay legible. */
export const DENSE_POINTS = 2000;

export interface Bounds { xMin: number; xMax: number; yMin: number; yMax: number }

/** Canvas-pixel centres `[x0, y0, x1, y1, ...]` of the points inside *b*. */
export function dotCenters(
  xs: Float64Array, ys: Float64Array, toX: (v: number) => number, toY: (v: number) => number, b: Bounds,
): Float64Array {
  const out: number[] = [];
  for (let i = 0; i < xs.length; i++) {
    const x = xs[i], y = ys[i];
    if (x >= b.xMin && x <= b.xMax && y >= b.yMin && y <= b.yMax) out.push(toX(x), toY(y));
  }
  return Float64Array.from(out);
}

/** Faceted mode draws no built-in points, so each group fills one path of
 *  circles itself (as uPlot's own scatter demo does). */
function dotsPath(size: number): uPlot.Series.PathBuilder {
  return (u, seriesIdx) => {
    const [xs, ys] = u.data[seriesIdx] as unknown as [Float64Array, Float64Array];
    const { x, y } = u.scales;
    const centers = dotCenters(
      xs, ys, (v) => u.valToPos(v, "x", true), (v) => u.valToPos(v, "y", true),
      { xMin: x.min ?? -Infinity, xMax: x.max ?? Infinity, yMin: y.min ?? -Infinity, yMax: y.max ?? Infinity },
    );
    const r = (size / 2) * (globalThis.devicePixelRatio || 1);
    const fill = new Path2D();
    for (let i = 0; i < centers.length; i += 2) {
      fill.moveTo(centers[i] + r, centers[i + 1]);
      fill.arc(centers[i], centers[i + 1], r, 0, 2 * Math.PI);
    }
    return { fill, flags: 0 } as uPlot.Series.Paths;
  };
}

export function scatterData(groups: PointGroup[]): uPlot.AlignedData {
  return [null, ...groups.map((g) => [g.xs, g.ys])] as unknown as uPlot.AlignedData;
}

/** One point series per colour; *dense* draws smaller points. */
export function scatterOptions(
  colors: string[], { height, theme, dense = false, read }: {
    height: number; theme: ChartTheme; dense?: boolean; read?: (name: string) => string;
  },
): Omit<uPlot.Options, "width"> {
  const size = dense ? 3 : 7;
  return {
    mode: 2,
    height,
    legend: { show: false },
    cursor: { drag: { x: true, y: true, setScale: true }, points: { show: false } },
    scales: { x: { time: false } },
    axes: [themedAxis(theme, read), themedAxis(theme, read, { size: Y_AXIS_SIZE })],
    series: [
      {},
      ...colors.map((color): uPlot.Series => {
        const c = resolveCssColor(color, read);
        return { stroke: c, fill: c, width: 0, paths: dotsPath(size), points: { show: false, fill: c } };
      }),
    ],
  };
}
