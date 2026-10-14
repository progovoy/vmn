/** Parallel coordinates of the job's varying params and a metric (plan 23
 *  W4). A brush becomes a query clause, and "Show N brushed runs in Runs"
 *  opens the Runs tab filtered by it. */
import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import ChartGroupLegend from "../../components/ChartGroupLegend";
import ParallelCoordinates from "../../components/ParallelCoordinates";
import type { ExperimentColumns } from "../../types";
import { plural } from "../../util";
import {
  ChartEmpty, ChartFigure, ColorPicker, ColumnsState, colorChoice, MetricPicker, runsCaption, type JobChartProps,
} from "./JobChartParts";
import { useJobColumns } from "./jobChartQueries";
import { colorBy, colorKey, jobChartKeys, jobRows } from "./jobChartData";

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
  const groups = useMemo(() => colorBy(rows, colorKey(color)), [rows, color]);
  const [brushed, setBrushed] = useState<number | null>(null);
  const [query, setQuery] = useState<string | null>(null);
  // Stable props: a brush commit re-renders this, and must not rebuild 50k rows' axes.
  const metricCols = useMemo(() => [y], [y]);
  const onBrush = useCallback((idx: number[] | null) => setBrushed(idx ? idx.length : null), []);
  if (!rows.length) return <ChartEmpty text="No run of this outer run is in yet." />;
  return (
    <ChartFigure
      label={`Parallel coordinates of ${y} and ${plural(dims.length, "param")}, coloured by ${color}`}
      caption={<>{runsCaption(rows.length, data)}. Drag along an axis to brush; brushes on several axes combine. <BrushLink query={query} count={brushed ?? 0} /></>}
    >
      <ChartGroupLegend legend={groups.legend} />
      <ParallelCoordinates
        rows={rows} metricCols={metricCols} paramCols={dims} schema={null} groups={groups}
        onBrush={onBrush} onBrushQuery={setQuery}
      />
    </ChartFigure>
  );
}

export default function JobParallel(p: JobChartProps) {
  const color = colorChoice(p.state, p.groupable);
  const dims = useMemo(() => (p.varying.length ? p.varying : p.params).slice(0, MAX_PARAM_AXES), [p.varying, p.params]);
  const keys = useMemo(() => jobChartKeys({
    chart: "parallel", x: "", y: p.y, color: colorKey(color), params: dims,
  }), [p.y, color, dims]);
  const query = useJobColumns(p.ws, p.app, p.summary.verstr, keys, p.summary);
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
