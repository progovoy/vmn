import { memo, useMemo, useState } from "react";
import {
  CartesianGrid, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from "recharts";
import type { ExperimentRow, MetricsSchema } from "../types";
import { fmtVal, metricGoal, paramValue } from "../util";
import { finiteOrNull, maxOf, minOf } from "../util/stats";
import { clickedVerstr, useContainerWidth, useRunSelect } from "./chartHooks";

interface Props {
  rows: ExperimentRow[];
  metricCols: string[];
  paramCols: string[];
  schema: MetricsSchema | null;
  /** Called with a clicked point's run; defaults to opening the run page. */
  onSelect?: (verstr: string) => void;
}

function numericValue(row: ExperimentRow, col: string, paramCols: string[]): number | null {
  return finiteOrNull(paramCols.includes(col) ? paramValue(row, col) : row.metrics[col]);
}

function MetricScatter({ rows, metricCols, paramCols, schema, onSelect }: Props) {
  const [wrapRef, width] = useContainerWidth<HTMLDivElement>(480);
  const select = useRunSelect(onSelect);
  const onPointClick = (entry: unknown) => {
    const v = clickedVerstr(entry);
    if (v) select(v);
  };
  const allCols = useMemo(() => [...metricCols, ...paramCols], [metricCols, paramCols]);

  const defaultX = metricCols[0] ?? paramCols[0] ?? "";
  const defaultY = metricCols[1] ?? paramCols[0] ?? metricCols[0] ?? "";

  const [xCol, setXCol] = useState(defaultX);
  const [yCol, setYCol] = useState(defaultY);

  const yGoal = metricGoal(schema, yCol);

  const data = useMemo(() =>
    rows
      .map((r) => {
        const x = numericValue(r, xCol, paramCols);
        const y = numericValue(r, yCol, paramCols);
        if (x === null || y === null) return null;
        return { x, y, verstr: r.verstr };
      })
      .filter((d): d is { x: number; y: number; verstr: string } => d !== null),
    [rows, xCol, yCol, paramCols]
  );

  const bestY = useMemo(() => {
    if (data.length === 0) return null;
    const vals = data.map((d) => d.y);
    return yGoal === "min" ? minOf(vals) : maxOf(vals);
  }, [data, yGoal]);

  const large = data.length > 2000;

  const bestData = useMemo(
    () => data.filter((d) => d.y === bestY),
    [data, bestY]
  );
  const restData = useMemo(
    () => data.filter((d) => d.y !== bestY),
    [data, bestY]
  );

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <div className="eyebrow" style={{ marginBottom: 0 }}>scatter plot</div>
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
          X
          <select
            role="combobox"
            value={xCol}
            onChange={(e) => setXCol(e.target.value)}
            style={{ minWidth: 80 }}
          >
            {allCols.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
          Y
          <select
            role="combobox"
            value={yCol}
            onChange={(e) => setYCol(e.target.value)}
            style={{ minWidth: 80 }}
          >
            {allCols.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      </div>
      <div ref={wrapRef} style={{ width: "100%" }}>
        <ScatterChart width={width} height={320} margin={{ left: 10, right: 20, top: 10, bottom: 10 }}>
          <CartesianGrid stroke="var(--line)" />
          <XAxis
            type="number" dataKey="x" name={xCol} stroke="var(--text-3)"
            tick={{ fontSize: 10, fontFamily: "var(--mono)" }}
          />
          <YAxis
            type="number" dataKey="y" name={yCol} stroke="var(--text-3)"
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
          <Scatter
            data={restData}
            fill="var(--accent)"
            isAnimationActive={false}
            cursor="pointer"
            onClick={onPointClick}
            shape={large ? <circle r={2} /> : undefined}
          />
          <Scatter
            data={bestData}
            fill="var(--good)"
            isAnimationActive={false}
            cursor="pointer"
            onClick={onPointClick}
            shape={large ? <circle r={3} /> : undefined}
          />
        </ScatterChart>
      </div>
    </div>
  );
}

/** Memoized: the leaderboard re-polls, and identical rows must not re-render
 *  thousands of SVG symbols. */
export default memo(MetricScatter);
