/** Pure uPlot configuration for the metric scatter: points only, one series
 *  per point group, each with its own x/y arrays (faceted mode). */
import type uPlot from "uplot";
import { resolveCssColor, type ChartTheme } from "./cssColor";
import { themedAxis, Y_AXIS_SIZE } from "./curveOptions";
import type { PointGroup } from "./scatterData";

/** Past this many points they are drawn smaller, so dense clouds stay legible. */
export const DENSE_POINTS = 2000;

const noLine: uPlot.Series.PathBuilder = () => null;

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
        return { stroke: c, paths: noLine, points: { show: true, size, fill: c, stroke: c, width: 0 } };
      }),
    ],
  };
}
