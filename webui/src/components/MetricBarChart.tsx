import { useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Tooltip, XAxis, YAxis,
} from "recharts";
import type { ExperimentRow, MetricsSchema } from "../types";
import { fmtVal, metricGoal } from "../util";

export default function MetricBarChart({ rows, metricCols, schema }: {
  rows: ExperimentRow[];
  metricCols: string[];
  schema: MetricsSchema | null;
}) {
  const [metric, setMetric] = useState(metricCols[0] ?? "");

  const goal = metricGoal(schema, metric);

  const data = useMemo(() =>
    rows
      .map((r) => ({
        label: `@${r.idx}`,
        value: typeof r.metrics[metric] === "number" ? r.metrics[metric] as number : null,
        verstr: r.verstr,
      }))
      .filter((d) => d.value !== null),
    [rows, metric]
  );

  const best = useMemo(() => {
    const vals = data.map((d) => d.value).filter((v): v is number => v !== null);
    if (vals.length === 0) return null;
    return goal === "min" ? Math.min(...vals) : Math.max(...vals);
  }, [data, goal]);

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
      <div style={{ width: "100%", overflowX: "auto" }}>
        <BarChart width={480} height={Math.max(180, data.length * 28)} data={data} layout="vertical" margin={{ left: 10, right: 20 }}>
          <CartesianGrid stroke="var(--line)" horizontal={false} />
          <XAxis type="number" stroke="#85847a" tick={{ fontSize: 10, fontFamily: "var(--mono)" }} />
          <YAxis type="category" dataKey="label" width={50} stroke="#85847a" tick={{ fontSize: 10, fontFamily: "var(--mono)" }} />
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
          <Bar dataKey="value" isAnimationActive={false} radius={[0, 4, 4, 0]}>
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
