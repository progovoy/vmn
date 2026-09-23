import { useMemo } from "react";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { ExperimentRow, MetricsSchema } from "../types";
import { fmtVal, metricGoal, seriesColor } from "../util";
import { downsampleLTTB } from "../util/downsample";
import { maxOf, minOf } from "../util/stats";

/** One small chart per metric — each on its own scale, so a loss (~0.1) and
 *  an accuracy (~0.9) don't get squashed onto a shared axis. Same visual
 *  language as the run-detail training curves, in a small-multiples grid. */
export default function ParamPlots({ rows, metricCols, schema }: {
  rows: ExperimentRow[]; metricCols: string[]; schema: MetricsSchema | null;
}) {
  const plotCols = useMemo(
    () => metricCols.filter(
      (m) => {
        let n = 0;
        for (const r of rows) if (typeof r.metrics[m] === "number" && ++n > 1) return true;
        return false;
      }
    ),
    [rows, metricCols]
  );
  const points = useMemo(
    () => [...rows].sort((a, b) => a.idx - b.idx),
    [rows]
  );

  if (plotCols.length === 0) return null;

  return (
    <div className="card">
      <div className="eyebrow">metrics across runs</div>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
        gap: 20,
      }}>
        {plotCols.map((m) => {
          const goal = metricGoal(schema, m);
          const color = seriesColor(plotCols, m);
          const data = points.map((r) => ({ x: r.idx, v: r.metrics[m] as number | null | undefined }));
          const chartData = downsampleLTTB(
            data.filter((d): d is { x: number; v: number } =>
              typeof d.v === "number" && Number.isFinite(d.v))
                .map(d => ({ x: d.x, y: d.v })),
            200
          ).map(d => ({ x: d.x, v: d.y }));
          const vals = data.map((d) => d.v);
          const extreme = goal === "min" ? minOf(vals) : maxOf(vals);
          const best = Number.isNaN(extreme) ? null : extreme;
          return (
            <div key={m}>
              <div style={{
                display: "flex", alignItems: "baseline", justifyContent: "space-between",
                marginBottom: 6, fontSize: 12,
              }}>
                <span className="mono" style={{ color: "var(--text-2)" }}>
                  {m}{" "}
                  <span style={{ color: "var(--text-3)" }}>{goal === "min" ? "↓" : "↑"}</span>
                </span>
                {best !== null && (
                  <span style={{ color: "var(--good)", fontSize: 11 }}>best {fmtVal(best)}</span>
                )}
              </div>
              <ResponsiveContainer width="100%" height={110}>
                <LineChart data={chartData}>
                  <CartesianGrid stroke="var(--line)" vertical={false} />
                  <XAxis dataKey="x" hide />
                  <YAxis
                    width={34} stroke="#85847a"
                    tick={{ fontSize: 10, fontFamily: "var(--mono)" }}
                  />
                  <Tooltip
                    labelFormatter={(x) => `@${x}`}
                    formatter={(v: number) => fmtVal(v)}
                    contentStyle={{
                      background: "var(--panel-2)",
                      border: "1px solid var(--line)",
                      borderRadius: 8,
                      color: "var(--text)",
                      fontSize: 12,
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="v"
                    stroke={color}
                    strokeWidth={2}
                    dot={false}
                    connectNulls
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          );
        })}
      </div>
    </div>
  );
}
