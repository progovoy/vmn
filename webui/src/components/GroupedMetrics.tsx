import { useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ErrorBar, Tooltip, XAxis, YAxis,
} from "recharts";
import type { ExperimentRow, MetricsSchema } from "../types";
import { fmtVal, metricGoal, paramValue } from "../util";
import { finiteNumbers, maxOf, minOf } from "../util/stats";

function mean(vals: number[]): number {
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function std(vals: number[]): number {
  const m = mean(vals);
  return Math.sqrt(vals.reduce((a, b) => a + (b - m) ** 2, 0) / vals.length);
}

interface GroupStats {
  group: string;
  count: number;
  stats: Record<string, { mean: number; std: number; min: number; max: number }>;
}

function computeGroups(
  rows: ExperimentRow[],
  groupKey: string,
): GroupStats[] {
  const buckets = new Map<string, ExperimentRow[]>();

  for (const r of rows) {
    let val: string;
    if (groupKey === "branch") {
      val = r.branch ?? "(none)";
    } else {
      const p = paramValue(r, groupKey);
      val = p != null ? String(p) : "(none)";
    }
    const arr = buckets.get(val);
    if (arr) arr.push(r);
    else buckets.set(val, [r]);
  }

  const result: GroupStats[] = [];
  for (const [group, bucket] of buckets) {
    const metricKeys = new Set<string>();
    for (const r of bucket) {
      for (const k of Object.keys(r.metrics)) metricKeys.add(k);
    }

    const stats: GroupStats["stats"] = {};
    for (const k of metricKeys) {
      const vals = finiteNumbers(bucket.map((r) => r.metrics[k]));
      if (vals.length === 0) continue;
      stats[k] = {
        mean: mean(vals),
        std: std(vals),
        min: minOf(vals),
        max: maxOf(vals),
      };
    }

    result.push({ group, count: bucket.length, stats });
  }

  return result;
}

export default function GroupedMetrics({ rows, metricCols, paramCols, schema }: {
  rows: ExperimentRow[];
  metricCols: string[];
  paramCols: string[];
  schema: MetricsSchema | null;
}) {
  const groupOptions = useMemo(
    () => ["branch", ...paramCols],
    [paramCols],
  );

  const [groupKey, setGroupKey] = useState("branch");
  const [chartMetric, setChartMetric] = useState(metricCols[0] ?? "");

  const groups = useMemo(
    () => computeGroups(rows, groupKey),
    [rows, groupKey],
  );

  const chartData = useMemo(
    () =>
      groups.map((g) => {
        const s = g.stats[chartMetric];
        return {
          group: g.group,
          mean: s?.mean ?? 0,
          errorY: s?.std ?? 0,
        };
      }),
    [groups, chartMetric],
  );

  if (rows.length === 0) {
    return (
      <div className="card">
        <div className="eyebrow" style={{ marginBottom: 0 }}>grouped metrics</div>
        <p style={{ color: "var(--text-3)", marginTop: 8 }}>No groups to show.</p>
      </div>
    );
  }

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
        <div className="eyebrow" style={{ marginBottom: 0 }}>grouped metrics</div>
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
          Group by
          <select
            value={groupKey}
            onChange={(e) => setGroupKey(e.target.value)}
            style={{ minWidth: 90 }}
          >
            {groupOptions.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
          Metric
          <select
            value={chartMetric}
            onChange={(e) => setChartMetric(e.target.value)}
            style={{ minWidth: 90 }}
          >
            {metricCols.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </label>
      </div>

      <div style={{ width: "100%", overflowX: "auto", marginBottom: 16 }}>
        <BarChart
          width={Math.max(320, groups.length * 80)}
          height={220}
          data={chartData}
          margin={{ left: 10, right: 20, top: 10, bottom: 5 }}
        >
          <CartesianGrid stroke="var(--line)" vertical={false} />
          <XAxis
            dataKey="group"
            stroke="#85847a"
            tick={{ fontSize: 11, fontFamily: "var(--mono)" }}
          />
          <YAxis
            stroke="#85847a"
            tick={{ fontSize: 10, fontFamily: "var(--mono)" }}
          />
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
            dataKey="mean"
            fill={metricGoal(schema, chartMetric) === "min" ? "var(--hotfix)" : "var(--minor)"}
            fillOpacity={0.7}
            isAnimationActive={false}
            radius={[4, 4, 0, 0]}
          >
            <ErrorBar dataKey="errorY" stroke="var(--text-2)" strokeWidth={1.5} />
          </Bar>
        </BarChart>
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ minWidth: 400 }}>
          <thead>
            <tr>
              <th>{groupKey}</th>
              <th className="num">n</th>
              {metricCols.map((m) => (
                <th key={m} className="num">{m}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <tr key={g.group}>
                <td>{g.group}</td>
                <td className="num">{g.count}</td>
                {metricCols.map((m) => {
                  const s = g.stats[m];
                  if (!s) return <td key={m} className="num">--</td>;
                  return (
                    <td key={m} className="num" style={{ fontFamily: "var(--mono)", fontSize: 12 }}>
                      {fmtVal(s.mean)} {"±"} {fmtVal(s.std)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
