/** Parallel coordinates of the job's varying params and a metric (plan 23
 *  W4). A brush becomes a query clause, and "Show N brushed runs in Runs"
 *  opens the Runs tab filtered by it. */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import ChartGroupLegend from "../../components/ChartGroupLegend";
import ParallelCoordinates from "../../components/ParallelCoordinates";
import type { ExperimentColumns } from "../../types";
import { plural } from "../../util";
import {
  ChartEmpty, ChartFigure, ColorPicker, ColumnsState, colorChoice, MetricPicker, runsCaption, type JobChartProps,
} from "./JobChartParts";
import { useJobColumns } from "./jobChartQueries";
import { colorBy, jobChartKeys, jobRows } from "./jobChartData";

/** Axes past this many are left off (each needs ~100px). */
const MAX_PARAM_AXES = 12;

function BrushLink({ query, count }: { query: string | null; count: number }) {
  if (!query || !count) return null;
  return (
    <Link className="job-brush-link" to={{ search: `?${new URLSearchParams({ tab: "runs", q: query })}` }}>
      Show {plural(count, "brushed run")} in Runs
    </Link>
  );
}

function Plot({ data, dims, color, y }: { data: ExperimentColumns; dims: string[]; color: string; y: string }) {
  const rows = useMemo(() => jobRows(data), [data]);
  const groups = useMemo(() => colorBy(rows, color === "status" ? "status" : `params.${color}`), [rows, color]);
  const [brushed, setBrushed] = useState<number | null>(null);
  const [query, setQuery] = useState<string | null>(null);
  if (!rows.length) return <ChartEmpty text="No run of this job is in yet." />;
  return (
    <ChartFigure
      label={`Parallel coordinates of ${y} and ${plural(dims.length, "param")}, coloured by ${color}`}
      caption={<>{runsCaption(rows.length, data)}. Drag along an axis to brush; brushes on several axes combine. <BrushLink query={query} count={brushed ?? 0} /></>}
    >
      <ChartGroupLegend legend={groups.legend} />
      <ParallelCoordinates
        rows={rows} metricCols={[y]} paramCols={dims} schema={null} groups={groups}
        onBrush={(idx) => setBrushed(idx ? idx.length : null)} onBrushQuery={setQuery}
      />
    </ChartFigure>
  );
}

export default function JobParallel(p: JobChartProps) {
  const color = colorChoice(p.state, p.groupable);
  const dims = useMemo(() => (p.varying.length ? p.varying : p.params).slice(0, MAX_PARAM_AXES), [p.varying, p.params]);
  const keys = useMemo(() => jobChartKeys({
    chart: "parallel", x: "", y: p.y, color: color === "status" ? "status" : `params.${color}`, params: dims,
  }), [p.y, color, dims]);
  const query = useJobColumns(p.ws, p.app, p.summary.verstr, keys, p.summary.done);
  return (
    <>
      <div className="job-chart-tools">
        <MetricPicker metrics={p.metrics} y={p.y} state={p.state} />
        <ColorPicker value={color} groupable={p.groupable} state={p.state} />
      </div>
      <ColumnsState query={query}>{(data) => <Plot data={data} dims={dims} color={color} y={p.y} />}</ColumnsState>
    </>
  );
}
