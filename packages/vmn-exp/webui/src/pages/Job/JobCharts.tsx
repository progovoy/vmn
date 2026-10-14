/** The job's Charts tab (plan 23 W4): every run of the job's subtree on one
 *  chart at a time, the chart and its axes in the URL (`chart`, `x`, `y`,
 *  `color`, `k`). The param/metric vocabulary comes from the scoped facets,
 *  the main metric from the job's summary. */
import { useMemo } from "react";
import type { JobSummary } from "../../apiJob";
import Segmented from "../../components/Segmented";
import { Skeleton } from "../../components/ui";
import type { ExperimentFacets } from "../../types";
import { MAX_PARAM_VALUES } from "../../util/groupBy";
import JobBoxByParam from "./JobBoxByParam";
import { ChartEmpty, type JobChartProps } from "./JobChartParts";
import { type JobChart } from "./jobChartData";
import { useJobChartState, useJobFacets } from "./jobChartQueries";
import JobCurves from "./JobCurves";
import { mainMetric } from "./jobData";
import JobParallel from "./JobParallel";
import JobScatter from "./JobScatter";

const CHART_OPTIONS: readonly (readonly [JobChart, string])[] = [
  ["scatter", "Scatter"], ["parallel", "Parallel"], ["curves", "Curves"], ["bypar", "By param"],
];

const CHARTS: Record<JobChart, (p: JobChartProps) => JSX.Element> = {
  scatter: JobScatter, parallel: JobParallel, curves: JobCurves, bypar: JobBoxByParam,
};

/** The job's metrics (the facets', else the summary's) and its params by spread. */
function vocabulary(summary: JobSummary, facets: ExperimentFacets | undefined) {
  const tracked = Object.keys(summary.metrics).filter((m) => summary.metrics[m]);
  const metrics = [...new Set([...tracked, ...(facets?.metric_keys ?? [])])];
  const params = facets?.param_keys ?? [];
  const values = (p: string) => facets?.param_values?.[p] ?? 2;
  return {
    metrics,
    params,
    varying: params.filter((p) => values(p) > 1),
    groupable: params.filter((p) => values(p) > 1 && values(p) <= MAX_PARAM_VALUES),
  };
}

export default function JobCharts({ ws, app, summary }: { ws: string; app: string; summary: JobSummary }) {
  const state = useJobChartState();
  const facets = useJobFacets(ws, app, summary.verstr);
  // Every poll brings a new summary; the charts keep the same name lists
  // (and so their 50k-row memos) until a name really changes.
  const fresh = vocabulary(summary, facets.data);
  const names = JSON.stringify(fresh);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const vocab = useMemo(() => fresh, [names]);

  if (facets.isPending) return <Skeleton />;
  if (!vocab.metrics.length) return <ChartEmpty text="No run of this job has logged a metric yet." />;
  const main = mainMetric(summary);
  const y = state.y && vocab.metrics.includes(state.y) ? state.y
    : main && vocab.metrics.includes(main) ? main : vocab.metrics[0];
  const Chart = CHARTS[state.chart];
  return (
    <section className="card job-charts" aria-label="Charts">
      <div className="job-chart-tools">
        <Segmented label="Chart" options={CHART_OPTIONS} value={state.chart} onChange={(chart) => state.set({ chart })} />
      </div>
      <Chart ws={ws} app={app} summary={summary} {...vocab} y={y} state={state} />
    </section>
  );
}
