/** The job's Overview tab (plan 23 §3.2): its answers, all from the rollup
 *  — KPI tiles (and, with a split, per value: plan 28 P3), progress over time, the main metric's distribution, the top
 *  runs, the top failure clusters, a pivot heatmap of two fields (plan 28 N2) and, for a sweep, the params that matter.
 *  (Best-so-far by completion order is not in the §10 contract: left out.) */
import { useMemo, type ReactNode } from "react";
import type { JobPageSummary } from "../../apiJob";
import { runHref } from "../../util";
import { failedCount, mainMetric } from "./jobData";
import JobKpiTiles from "./JobKpiTiles";
import JobMetricHistogram from "./JobMetricHistogram";
import JobPivot from "./JobPivot";
import JobSplitTable from "./JobSplitTable";
import { JobFailureTop, JobImportance } from "./JobOverviewParts";
import { jobTabHref } from "./jobQueries";
import JobTimelineChart from "./JobTimelineChart";
import JobTopRuns from "./JobTopRuns";

function Card({ title, wide, children }: { title: string; wide?: boolean; children: ReactNode }) {
  return (
    <section className={`card job-card${wide ? " wide" : ""}`} aria-label={title}>
      <h2 className="job-card-title">{title}</h2>
      {children}
    </section>
  );
}

export default function JobOverview({ ws, app, summary }: { ws: string; app: string; summary: JobPageSummary }) {
  const appBase = `/ws/${ws}/app/${app}`;
  const runBase = runHref(appBase, summary.verstr);
  const metric = mainMetric(summary);
  const metricNames = useMemo(() => Object.keys(summary.metrics), [summary.metrics]);
  return (
    <div className="job-overview">
      <JobKpiTiles summary={summary} runBase={appBase} />
      <JobSplitTable summary={summary} runBase={runBase} />
      <div className="job-grid">
        <Card title="Progress over time"><JobTimelineChart timeline={summary.timeline} /></Card>
        <Card title="Distribution"><JobMetricHistogram metrics={summary.metrics} initial={metric} /></Card>
        <Card title={metric ? `Top runs on ${metric}` : "Top runs"}>
          <JobTopRuns top={summary.top} metric={metric} ranked={summary.ranked !== false} appBase={appBase} allHref={jobTabHref(runBase, "runs")} />
        </Card>
        <Card title="Failure clusters">
          <JobFailureTop ws={ws} app={app} verstr={summary.verstr} failed={failedCount(summary)} failuresHref={jobTabHref(runBase, "failures")} />
        </Card>
        <Card title="Pivot" wide>
          <JobPivot ws={ws} app={app} verstr={summary.verstr} metrics={metricNames} done={summary.done} expected={summary.expected} />
        </Card>
        {summary.sweep && (
          <Card title="Params that matter" wide>
            <JobImportance ws={ws} app={app} verstr={summary.verstr} metric={metric} done={summary.done} />
          </Card>
        )}
      </div>
    </div>
  );
}
