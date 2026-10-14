/** A metric's distribution per value of a param (plan 23 W4): one box per
 *  value (min, quartiles, median, max) on a shared axis, at most 20 values,
 *  grouped client-side from the scoped columns. */
import { useMemo } from "react";
import type { ExperimentColumns } from "../../types";
import { fmtVal, plural } from "../../util";
import {
  ChartEmpty, ChartFigure, ColumnsState, MetricPicker, Picker, runsCaption, type JobChartProps,
} from "./JobChartParts";
import { useJobColumns } from "./jobChartQueries";
import { boxGroups, jobChartKeys, jobRows, type Box } from "./jobChartData";

function BoxRow({ box, at }: { box: Box; at: (v: number) => number }) {
  const tip = `${box.label}: ${plural(box.n, "run")}, median ${fmtVal(box.median)}`
    + ` (quartiles ${fmtVal(box.q1)} – ${fmtVal(box.q3)}, range ${fmtVal(box.min)} – ${fmtVal(box.max)})`;
  return (
    <div className="job-box-row" title={tip}>
      <span className="job-box-label">{box.label}</span>
      <span className="job-box-track">
        <span className="job-box-whisker" style={{ left: `${at(box.min)}%`, width: `${at(box.max) - at(box.min)}%` }} />
        <span className="job-box-iqr" style={{ left: `${at(box.q1)}%`, width: `${Math.max(at(box.q3) - at(box.q1), 0.5)}%` }} />
        <span className="job-box-median" style={{ left: `${at(box.median)}%` }} />
      </span>
      <span className="job-box-n">{box.n.toLocaleString("en-US")}</span>
    </div>
  );
}

function BoxTable({ groups, param }: { groups: Box[]; param: string }) {
  return (
    <table className="sr-only">
      <thead><tr><th scope="col">{param}</th><th scope="col">runs</th><th scope="col">min</th><th scope="col">median</th><th scope="col">max</th></tr></thead>
      <tbody>
        {groups.map((b) => (
          <tr key={b.label}><td>{b.label}</td><td>{b.n}</td><td>{fmtVal(b.min)}</td><td>{fmtVal(b.median)}</td><td>{fmtVal(b.max)}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function Plot({ data, param, y }: { data: ExperimentColumns; param: string; y: string }) {
  const { groups, dropped } = useMemo(() => boxGroups(jobRows(data), `params.${param}`, y), [data, param, y]);
  if (!groups.length) return <ChartEmpty text={`No run of this outer run has both ${param} and ${y} yet.`} />;
  const lo = Math.min(...groups.map((b) => b.min)), hi = Math.max(...groups.map((b) => b.max));
  const at = (v: number) => (hi > lo ? ((v - lo) / (hi - lo)) * 100 : 50);
  const runs = groups.reduce((n, b) => n + b.n, 0);
  const more = dropped ? ` ${plural(dropped, "rarer value")} left out.` : "";
  return (
    <ChartFigure
      label={`${y} by ${param}: ${plural(groups.length, "value")}`}
      caption={`${y} per value of ${param} over ${runsCaption(runs, data)}: whiskers span min to max, the box the middle half, the tick the median.${more}`}
    >
      <div className="job-boxes" aria-hidden="true">
        <div className="job-box-row job-box-head"><span>{param}</span><span /><span>runs</span></div>
        {groups.map((b) => <BoxRow key={b.label} box={b} at={at} />)}
        <div className="job-box-row"><span /><span className="job-axis-x"><span>{fmtVal(lo)}</span><span>{fmtVal(hi)}</span></span><span /></div>
      </div>
      <BoxTable groups={groups} param={param} />
    </ChartFigure>
  );
}

export default function JobBoxByParam(p: JobChartProps) {
  const param = p.state.x && p.groupable.includes(p.state.x) ? p.state.x : p.groupable[0] ?? null;
  const keys = useMemo(
    () => (param ? jobChartKeys({ chart: "bypar", x: `params.${param}`, y: p.y, color: "", params: [] }) : []),
    [param, p.y],
  );
  const query = useJobColumns(p.ws, p.app, p.summary.verstr, keys, p.summary);
  return (
    <>
      <div className="job-chart-tools">
        <MetricPicker metrics={p.metrics} y={p.y} state={p.state} />
        {param && <Picker label="Param" value={param} options={p.groupable} onChange={(x) => p.state.set({ x })} />}
      </div>
      {param
        ? <ColumnsState query={query}>{(data) => <Plot data={data} param={param} y={p.y} />}</ColumnsState>
        : <ChartEmpty text="No param of this outer run takes between 2 and 20 values to group by." />}
    </>
  );
}
