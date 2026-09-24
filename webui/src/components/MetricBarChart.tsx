import { memo, useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Tooltip, XAxis, YAxis,
} from "recharts";
import type { ExperimentRow, MetricsSchema } from "../types";
import { fmtVal, metricGoal } from "../util";
import { isFiniteNumber } from "../util/stats";
import { useContainerWidth, useRunClick } from "./chartHooks";

/** One bar per run stops being readable (and renderable) long before 50k runs. */
export const MAX_BARS = 50;

function MetricBarChart({ rows, metricCols, schema, onSelect }: {
  rows: ExperimentRow[];
  metricCols: string[];
  schema: MetricsSchema | null;
  /** Called with a clicked bar's run; defaults to opening the run page. */
  onSelect?: (verstr: string) => void;
}) {
  const [metric, setMetric] = useState(metricCols[0] ?? "");
  const [wrapRef, width] = useContainerWidth<HTMLDivElement>(480);
  const onBarClick = useRunClick(onSelect);

  const goal = metricGoal(schema, metric);

  const { data, total } = useMemo(() => {
    const all = rows
      .map((r) => ({ label: `@${r.idx}`, value: r.metrics[metric], verstr: r.verstr }))
      .filter((d): d is { label: string; value: number; verstr: string } =>
        isFiniteNumber(d.value));
    const best = [...all].sort((a, b) => (goal === "min" ? a.value - b.value : b.value - a.value));
    return { data: best.slice(0, MAX_BARS), total: all.length };
  }, [rows, metric, goal]);

  // `data` is sorted best-first, so the best value is its head.
  const best = data.length ? data[0].value : null;

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div className="eyebrow" style={{ marginBottom: 0 }}>metric bar chart</div>
        <select
          role="combobox"
          value={metric}
          onChange={(e) => setMetric(e.target.value)}
          style={{ minWidth: 100 }}
        >
          {metricCols.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>
      {total > data.length && (
        <div style={{ color: "var(--text-3)", fontSize: 11, marginBottom: 6 }}>
          showing the top {MAX_BARS} of {total} runs by {metric}
        </div>
      )}
      <div ref={wrapRef} style={{ width: "100%" }}>
        <BarChart width={width} height={Math.max(180, data.length * 28)} data={data} layout="vertical" margin={{ left: 10, right: 20 }}>
          <CartesianGrid stroke="var(--line)" horizontal={false} />
          <XAxis type="number" stroke="var(--text-3)" tick={{ fontSize: 10, fontFamily: "var(--mono)" }} />
          <YAxis type="category" dataKey="label" width={50} stroke="var(--text-3)" tick={{ fontSize: 10, fontFamily: "var(--mono)" }} />
          <Tooltip
            formatter={(v: number) => fmtVal(v)}
            contentStyle={{
              background: "var(--panel-2)",
              border: "1px solid var(--line)",
              borderRadius: 8,
              color: "var(--text)",
              fontSize: 12,
            }}
          />
          <Bar
            dataKey="value"
            isAnimationActive={false}
            radius={[0, 4, 4, 0]}
            cursor="pointer"
            onClick={onBarClick}
          >
            {data.map((d, i) => (
              <Cell
                key={i}
                fill={d.value === best ? "var(--good)" : "var(--accent)"}
                fillOpacity={d.value === best ? 1 : 0.6}
              />
            ))}
          </Bar>
        </BarChart>
      </div>
    </div>
  );
}

export default memo(MetricBarChart);
