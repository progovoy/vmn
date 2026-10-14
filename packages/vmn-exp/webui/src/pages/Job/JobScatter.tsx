/** Param (or metric) vs metric over every run of the job (plan 23 W4), on
 *  canvas up to 50k points, coloured by status or a param; hover names the
 *  nearest run, click opens it. */
import { useMemo } from "react";
import ChartGroupLegend from "../../components/ChartGroupLegend";
import MetricScatter from "../../components/MetricScatter";
import type { ExperimentColumns } from "../../types";
import { isFiniteNumber } from "../../util/stats";
import { ChartEmpty, ChartFigure, ColorPicker, ColumnsState, colKey, colorChoice, runsCaption, type JobChartProps } from "./JobChartParts";
import { useJobColumns } from "./jobChartQueries";
import { colorBy, colorKey, columnValue, jobChartKeys, jobRows } from "./jobChartData";

/** The x axis: the URL's, else the first varying param, else another metric. */
function xChoice({ state, params, metrics, varying, y }: JobChartProps): string {
  if (state.x && (params.includes(state.x) || metrics.includes(state.x))) return state.x;
  return varying[0] ?? params[0] ?? metrics.find((m) => m !== y) ?? y;
}

function Plot({ data, x, y, color, p }: { data: ExperimentColumns; x: string; y: string; color: string; p: JobChartProps }) {
  const rows = useMemo(() => jobRows(data), [data]);
  const groups = useMemo(() => colorBy(rows, colorKey(color)), [rows, color]);
  const xKey = colKey(x, p.params);
  const points = useMemo(
    () => rows.filter((r) => isFiniteNumber(columnValue(r, xKey)) && isFiniteNumber(r.metrics[y])).length,
    [rows, xKey, y],
  );
  if (!points) return <ChartEmpty text={`No run of this outer run has both ${x} and ${y} yet.`} />;
  return (
    <ChartFigure
      label={`Scatter of ${y} against ${x}, coloured by ${color}`}
      caption={`${y} against ${x}: ${runsCaption(points, data)}. Hover a point for its run, click to open it; drag to zoom.`}
    >
      <ChartGroupLegend legend={groups.legend} />
      <MetricScatter
        rows={rows} metricCols={p.metrics} paramCols={p.params} schema={null} groups={groups}
        x={x} y={y} yCols={p.metrics} onAxes={(nx, ny) => p.state.set({ x: nx, y: ny })}
      />
    </ChartFigure>
  );
}

export default function JobScatter(p: JobChartProps) {
  const x = xChoice(p);
  const color = colorChoice(p.state, p.groupable);
  const keys = useMemo(() => jobChartKeys({
    chart: "scatter", x: colKey(x, p.params), y: p.y,
    color: colorKey(color), params: [],
  }), [x, p.params, p.y, color]);
  const query = useJobColumns(p.ws, p.app, p.summary.verstr, keys, p.summary);
  return (
    <>
      <div className="job-chart-tools"><ColorPicker value={color} groupable={p.groupable} state={p.state} /></div>
      <ColumnsState query={query}>{(data) => <Plot data={data} x={x} y={p.y} color={color} p={p} />}</ColumnsState>
    </>
  );
}
