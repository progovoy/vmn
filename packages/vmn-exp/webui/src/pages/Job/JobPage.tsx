/** The job page (plan 23 W2): what a run with children opens on. Answers
 *  first (the Overview, from the job's rollup), then the runs, charts,
 *  failures, and the job's own code and log, each tab in `?tab=`. */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import type { JobSummary } from "../../apiJob";
import LiveStatus from "../../components/LiveStatus";
import RunHeaderActions from "../../components/RunHeaderActions";
import RunLog from "../../components/RunLog";
import { sweepQuery } from "../../components/SweepSection";
import { Skeleton } from "../../components/ui";
import { useLiveScope } from "../../hooks/useLiveScope";
import { usePolling } from "../../hooks/usePolling";
import AddToReport from "../../reports/AddToReport";
import { runSpec } from "../../reports/viewSpecs";
import type { ExperimentDetail } from "../../types";
import { pollIntervalMs } from "../../util";
import { RunChangesSection } from "../RunLayout";
import JobFailures from "./JobFailures";
import JobHeader, { JOB_PANEL_ID, JobTabs, jobTabId } from "./JobHeader";
import { failedCount } from "./jobData";
import JobOverview from "./JobOverview";
import JobRuns from "./JobRuns";
import { jobSummaryKey, useJobTab, type JobTab } from "./jobQueries";
import "./job.css";

function Coming({ text, boardHref }: { text: string; boardHref: string }) {
  return (
    <div className="card job-coming">
      <p>{text}</p>
      <Link to={boardHref}>See the job&apos;s runs on the experiments board</Link>
    </div>
  );
}

function Panel({ tab, ws, app, detail, summary, live }: {
  tab: JobTab; ws: string; app: string; detail: ExperimentDetail; summary: JobSummary;
  /** The page's Pause, and its rollup refresh (the Runs tab's live changes move it too). */
  live: { paused: boolean; onPaused: (paused: boolean) => void; refresh: () => unknown };
}) {
  const v = detail.metadata.verstr;
  const boardHref = `/ws/${ws}/app/${app}?${new URLSearchParams({ q: sweepQuery(v) })}`;
  switch (tab) {
    case "overview": return <JobOverview ws={ws} app={app} summary={summary} />;
    case "runs": return <JobRuns ws={ws} app={app} verstr={v} paused={live.paused} onPaused={live.onPaused} onLive={live.refresh} />;
    case "charts": return <Coming text={"The job\u2019s charts are coming in W4."} boardHref={boardHref} />;
    case "failures": return <JobFailures ws={ws} app={app} verstr={v} failed={failedCount(summary)} />;
    case "code": return <RunChangesSection ws={ws} app={app} verstr={v} />;
    case "log": {
      const tail = detail.log_tail ?? detail.log ?? [];
      return <RunLog ws={ws} app={app} verstr={v} tail={tail} total={detail.log_total ?? tail.length} />;
    }
  }
}

export default function JobPage({ ws, app, detail, summary, refetchDetail }: {
  ws: string; app: string; detail: ExperimentDetail;
  summary: UseQueryResult<JobSummary>; refetchDetail: () => unknown;
}) {
  const client = useQueryClient();
  const v = detail.metadata.verstr;
  const [tab, setTab] = useJobTab();
  const [paused, setPaused] = useState(false);
  const data = summary.data;

  // The rollup moves while any run of the subtree runs: pushed by the
  // subtree's live events, else polled at the job's heartbeat cadence. Only
  // the rollup (the failures and importance follow its counts) and, on the
  // Log tab, the job's own detail are refetched.
  const running = (data?.tree_status ?? detail.status?.tree_status) === "running" || (data?.counts.running ?? 0) > 0;
  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: jobSummaryKey(ws, app, v) }),
    tab === "log" ? refetchDetail() : null,
  ]);
  // The Runs tab follows the subtree's events itself, and refreshes the rollup with them.
  const own = tab !== "runs";
  const live = useLiveScope({ ws, app, scope: v, enabled: own && running && !paused, onChange: refresh });
  usePolling(refresh, pollIntervalMs(detail.status?.heartbeat_interval_sec), own && running && !paused && !live.connected);

  if (!data) return <Skeleton />;
  return (
    <div className="job-page">
      <JobHeader
        ws={ws} app={app} summary={data}
        actions={(
          <RunHeaderActions ws={ws} app={app} verstr={v} command={detail.status?.command}>
            <AddToReport ws={ws} spec={() => runSpec(app, v)} />
            <LiveStatus
              running={running} paused={paused} updatedAt={summary.dataUpdatedAt}
              onPause={() => setPaused(true)} onResume={() => setPaused(false)} onRefresh={() => void refresh()}
            />
          </RunHeaderActions>
        )}
        tabs={<JobTabs tab={tab} onTab={setTab} />}
      />
      <div role="tabpanel" id={JOB_PANEL_ID} aria-labelledby={jobTabId(tab)} className="job-panel">
        <Panel tab={tab} ws={ws} app={app} detail={detail} summary={data} live={{ paused, onPaused: setPaused, refresh }} />
      </div>
    </div>
  );
}
