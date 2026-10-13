/** The job's Overview tab (plan 23 §3.2): its answers, all from the rollup
 *  — KPI tiles, progress over time, the main metric's distribution, the top
 *  runs, the top failure clusters and, for a sweep, the params that matter.
 *  (Best-so-far by completion order is not in the §10 contract: left out.) */
import type { ReactNode } from "react";
import type { JobSummary } from "../../apiJob";
import { runHref } from "../../util";
import { failedCount, mainMetric } from "./jobData";
import JobKpiTiles from "./JobKpiTiles";
import JobMetricHistogram from "./JobMetricHistogram";
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

export default function JobOverview({ ws, app, summary }: { ws: string; app: string; summary: JobSummary }) {
  const appBase = `/ws/${ws}/app/${app}`;
  const runBase = runHref(appBase, summary.verstr);
  const metric = mainMetric(summary);
  return (
    <div className="job-overview">
      <JobKpiTiles summary={summary} runBase={appBase} />
      <div className="job-grid">
        <Card title="Progress over time"><JobTimelineChart timeline={summary.timeline} /></Card>
        <Card title="Distribution"><JobMetricHistogram metrics={summary.metrics} initial={metric} /></Card>
        <Card title={metric ? `Top runs on ${metric}` : "Top runs"}>
          <JobTopRuns top={summary.top} metric={metric} appBase={appBase} allHref={jobTabHref(runBase, "runs")} />
        </Card>
        <Card title="Failure clusters">
          <JobFailureTop ws={ws} app={app} verstr={summary.verstr} failed={failedCount(summary)} failuresHref={jobTabHref(runBase, "failures")} />
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
