import { memo, useMemo } from "react";
import type { ExperimentRow, MetricsSchema } from "../types";
import { fmtVal, metricGoal, seriesColor } from "../util";
import type { CurveSeries } from "../util/curveOptions";
import { downsampleLTTB } from "../util/downsample";
import { isFiniteNumber, maxOf, minOf } from "../util/stats";
import CurveChart from "./CurveChart";
import LazyMount from "./LazyMount";

/** Points per small chart: a trend line, not a per-run readout. */
const PLOT_POINTS = 200;
const PLOT_H = 110;
const runLabel = (x: number) => `@${x}`;

interface Plot {
  metric: string;
  goal: "min" | "max";
  best: number | null;
  curves: CurveSeries[];
}

function hasTwoValues(rows: ExperimentRow[], m: string): boolean {
  let n = 0;
  for (const r of rows) if (typeof r.metrics[m] === "number" && ++n > 1) return true;
  return false;
}

function buildPlot(sorted: ExperimentRow[], metric: string, cols: string[], schema: MetricsSchema | null): Plot {
  const goal = metricGoal(schema, metric);
  const xy: { x: number; y: number }[] = [];
  for (const r of sorted) {
    const v = r.metrics[metric];
    if (isFiniteNumber(v)) xy.push({ x: r.idx, y: v });
  }
  const thin = downsampleLTTB(xy, PLOT_POINTS);
  const vals = xy.map((d) => d.y);
  const extreme = goal === "min" ? minOf(vals) : maxOf(vals);
  return {
    metric, goal,
    best: Number.isNaN(extreme) ? null : extreme,
    curves: [{
      key: metric, label: metric, color: seriesColor(cols, metric),
      xs: Float64Array.from(thin, (d) => d.x), ys: Float64Array.from(thin, (d) => d.y),
    }],
  };
}

/** One small chart per metric — each on its own scale, so a loss (~0.1) and
 *  an accuracy (~0.9) don't get squashed onto a shared axis. Same visual
 *  language as the run-detail training curves, in a small-multiples grid. */
function ParamPlots({ rows, metricCols, schema }: {
  rows: ExperimentRow[]; metricCols: string[]; schema: MetricsSchema | null;
}) {
  const plots = useMemo(() => {
    const cols = metricCols.filter((m) => hasTwoValues(rows, m));
    const sorted = [...rows].sort((a, b) => a.idx - b.idx);
    return cols.map((m) => buildPlot(sorted, m, cols, schema));
  }, [rows, metricCols, schema]);

  if (plots.length === 0) return null;

  return (
    <div className="card">
      <div className="eyebrow">metrics across runs</div>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
        gap: 20,
      }}>
        {plots.map(({ metric, goal, best, curves }) => (
          <div key={metric}>
            <div style={{
              display: "flex", alignItems: "baseline", justifyContent: "space-between",
              marginBottom: 6, fontSize: 12,
            }}>
              <span className="mono" style={{ color: "var(--text-2)" }}>
                {metric}{" "}
                <span style={{ color: "var(--text-3)" }}>{goal === "min" ? "↓" : "↑"}</span>
              </span>
              {best !== null && (
                <span style={{ color: "var(--good)", fontSize: 11 }}>best {fmtVal(best)}</span>
              )}
            </div>
            <LazyMount height={PLOT_H}>
              <CurveChart series={curves} xMode="step" height={PLOT_H} hideX formatX={runLabel} />
            </LazyMount>
          </div>
        ))}
      </div>
    </div>
  );
}

export default memo(ParamPlots);
