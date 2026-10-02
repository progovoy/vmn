/** Report panels that plot many runs' rows (pinned or a live query). */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { appTag } from "../api";
import { useChartRows } from "../hooks/useChartRows";
import type { ChartView } from "../hooks/useLeaderboardView";
import type { ExperimentRow, MetricsSchema } from "../types";
import { fmtParam, fmtVal } from "../util";
import MetricBarChart from "../components/MetricBarChart";
import MetricScatter from "../components/MetricScatter";
import ParallelCoordinates from "../components/ParallelCoordinates";
import ParamImportance from "../components/ParamImportance";
import GroupedMetrics from "../components/GroupedMetrics";
import type { PanelSpec, PinnedRuns, QueryRuns } from "./panelSpec";
import { bareKey, queryFilter, splitKeys, usePinnedRows, useSchema } from "./panelData";

type RowRender = (rows: ExperimentRow[], schema: MetricsSchema | null) => ReactNode;
type Cols = { metricCols: string[]; paramCols: string[] };
interface SourceProps extends Cols { ws: string; app: string; view: ChartView; children: RowRender }

const NO_ROWS: ExperimentRow[] = [];

function QueryRows({ ws, app, runs, view, metricCols, paramCols, children }: SourceProps & { runs: QueryRuns }) {
  // Nothing loaded and an unknown total: always fetch the whole filtered set.
  const { rows } = useChartRows(ws, app, queryFilter(runs), view, metricCols, paramCols, NO_ROWS, Infinity);
  return <>{children(runs.limit ? rows.slice(0, runs.limit) : rows, useSchema(ws, app))}</>;
}

function PinnedRowsSource({ ws, app, runs, children }: SourceProps & { runs: PinnedRuns }) {
  return <>{children(usePinnedRows(ws, app, runs.verstrs), useSchema(ws, app))}</>;
}

function RowsSource(props: SourceProps & { runs: PinnedRuns | QueryRuns }) {
  const { runs } = props;
  return "verstrs" in runs
    ? <PinnedRowsSource {...props} runs={runs} />
    : <QueryRows {...props} runs={runs} />;
}

function LeaderboardTable({ ws, app, rows, metricCols, paramCols }: Cols & {
  ws: string; app: string; rows: ExperimentRow[];
}) {
  return (
    <table className="panel-leaderboard">
      <thead>
        <tr>
          <th>run</th>
          {metricCols.map((c) => <th key={`m.${c}`}>{c}</th>)}
          {paramCols.map((c) => <th key={`p.${c}`}>{c}</th>)}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.verstr}>
            <td><Link to={`/ws/${ws}/app/${appTag(app)}/run/${encodeURIComponent(r.verstr)}`}>@{r.idx}</Link></td>
            {metricCols.map((c) => <td key={`m.${c}`} className="mono">{fmtVal(r.metrics[c])}</td>)}
            {paramCols.map((c) => <td key={`p.${c}`} className="mono">{fmtParam(r.params?.[c] ?? "–")}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

type RowSpec = Extract<PanelSpec, { type: "leaderboard" | "bar" | "scatter" | "parallel" | "importance" | "grouped" }>;

/** The columns a row panel needs, the chart view whose keys fetch them, and its chart. */
function plan(spec: RowSpec, ws: string): { view: ChartView; cols: Cols; render: (c: Cols) => RowRender } {
  switch (spec.type) {
    case "leaderboard": {
      const cols = { metricCols: spec.columns ?? [], paramCols: spec.params ?? [] };
      return { view: "scatter", cols, render: (c) => (rows) => <LeaderboardTable ws={ws} app={spec.app} rows={rows} {...c} /> };
    }
    case "bar":
      return { view: "bar", cols: splitKeys([spec.metric]),
        render: (c) => (rows, schema) => <MetricBarChart rows={rows} metricCols={c.metricCols} schema={schema} /> };
    case "scatter":
      return { view: "scatter", cols: splitKeys([spec.x, spec.y]),
        render: (c) => (rows, schema) => (
          <MetricScatter rows={rows} {...c} schema={schema} initialX={bareKey(spec.x)} initialY={bareKey(spec.y)} />
        ) };
    case "parallel":
      return { view: "parallel", cols: splitKeys(spec.columns),
        render: (c) => (rows, schema) => <ParallelCoordinates rows={rows} {...c} schema={schema} /> };
    case "grouped":
      return { view: "grouped", cols: splitKeys([spec.metric, spec.group_by]),
        render: (c) => (rows, schema) => <GroupedMetrics rows={rows} {...c} schema={schema} /> };
    case "importance": {
      const filter = "verstrs" in spec.runs ? {} : queryFilter(spec.runs);
      return { view: "importance", cols: splitKeys([spec.metric]),
        render: (c) => (rows, schema) => (
          <ParamImportance ws={ws} app={spec.app} filter={filter} rows={rows} {...c} schema={schema}
            defaultMetric={bareKey(spec.metric)} />
        ) };
    }
  }
}

export function RowPanel({ ws, spec }: { ws: string; spec: RowSpec }) {
  const { view, cols, render } = plan(spec, ws);
  return <RowsSource ws={ws} app={spec.app} runs={spec.runs} view={view} {...cols}>{render(cols)}</RowsSource>;
}

export const ROW_TYPES = new Set(["leaderboard", "bar", "scatter", "parallel", "importance", "grouped"]);
export type { RowSpec };
