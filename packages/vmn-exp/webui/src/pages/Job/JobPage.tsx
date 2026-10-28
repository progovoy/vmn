/** The job page (plan 23 W2): what a run with children opens on. Its header
 *  and tabs paint at once from what the index already holds (the job's
 *  row, else the summary); each tab fills in as its own data lands: the
 *  Overview, Charts and Failures from the job's rollup, the Runs from the
 *  scoped board, the Log from the job's run detail (read only there), each
 *  tab in `?tab=`. */
import { useState } from "react";
import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import type { JobPageSummary } from "../../apiJob";
import AttentionStrip from "../../components/AttentionStrip";
import LiveStatus from "../../components/LiveStatus";
import RunHeaderActions from "../../components/RunHeaderActions";
import RunLog from "../../components/RunLog";
import { Skeleton } from "../../components/ui";
import { useLiveOrPoll } from "../../hooks/useLiveOrPoll";
import { runQuery } from "../../queries";
import AddToReport from "../../reports/AddToReport";
import { runSpec } from "../../reports/viewSpecs";
import type { ExperimentDetail, ExperimentRow } from "../../types";
import { RunChangesSection } from "../RunLayout";
import JobCharts from "./JobCharts";
import JobFailures from "./JobFailures";
import JobHeader, { JOB_PANEL_ID, JobCliCard, JobTabs, jobTabId } from "./JobHeader";
import { failedCount } from "./jobData";
import { jobHead } from "./jobHead";
import JobOverview from "./JobOverview";
import JobRuns from "./JobRuns";
import { jobSummaryKey, onTabSearch, useJobTab, type JobTab } from "./jobQueries";
import { useScopedStatus } from "../../shell/useShellData";
import "./job.css";

function Panel({ tab, ws, app, v, name, detail, summary, live }: {
  tab: JobTab; ws: string; app: string; v: string; name?: string;
  detail: ExperimentDetail | undefined; summary: JobPageSummary | undefined;
  /** The page's Pause, and its rollup refresh (the Runs tab's live changes move it too). */
  live: { paused: boolean; onPaused: (paused: boolean) => void; refresh: () => unknown };
}) {
  switch (tab) {
    case "runs": return <JobRuns ws={ws} app={app} verstr={v} name={name} paused={live.paused} onPaused={live.onPaused} onLive={live.refresh} />;
    case "code": return <RunChangesSection ws={ws} app={app} verstr={v} />;
    case "log": {
      if (!detail) return <Skeleton />;
      const tail = detail.log_tail ?? detail.log ?? [];
      return <RunLog ws={ws} app={app} verstr={v} tail={tail} total={detail.log_total ?? tail.length} />;
    }
  }
  if (!summary) return <Skeleton />;
  switch (tab) {
    case "overview": return <JobOverview ws={ws} app={app} summary={summary} />;
    case "charts": return <JobCharts ws={ws} app={app} summary={summary} />;
    case "failures": return <JobFailures ws={ws} app={app} verstr={v} failed={failedCount(summary)} />;
  }
}

export default function JobPage({ ws, app, runRef, verstr: v, row, summary }: {
  ws: string; app: string;
  /** The URL's run ref (the run detail's cache key) and the job's verstr. */
  runRef: string; verstr: string;
  /** The index's row of the job, when known. */
  row?: ExperimentRow;
  summary: UseQueryResult<JobPageSummary>;
}) {
  const client = useQueryClient();
  const [tab, setTab] = useJobTab();
  const [paused, setPaused] = useState(false);
  const [followed, setFollowed] = useState(0);
  const { search } = useLocation();
  const scopedStatus = useScopedStatus(ws, app, v).data;
  const data = summary.data;
  // The detail is the job's own run (log, heartbeat): per-run store reads,
  // asked for by the Log tab only; a detail already cached is used anyway.
  const detailQuery = useQuery({ ...runQuery(ws, app, runRef), enabled: tab === "log" }, client);
  const detail = detailQuery.data;
  const { head, command, heartbeatSec } = jobHead(v, data, row, detail);

  // The rollup moves while any run of the subtree runs: pushed by the
  // subtree's live events, else polled at the job's heartbeat cadence. Only
  // the rollup (the failures and importance follow its counts) and, on the
  // Log tab, the job's own detail are refetched.
  const running = head.tree_status === "running" || (data?.counts.running ?? 0) > 0;
  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: jobSummaryKey(ws, app, v) }),
    tab === "log" ? detailQuery.refetch() : null,
  ]);
  // The Runs tab follows the subtree's events itself, and refreshes the rollup with them.
  const own = tab !== "runs";
  useLiveOrPoll({
    ws, app, scope: v, enabled: own && running && !paused,
    heartbeatSec, refresh,
  });

  return (
    <div className="job-page">
      <JobHeader
        summary={head}
        actions={(
          <RunHeaderActions ws={ws} app={app} verstr={v} command={command}>
            <AddToReport ws={ws} spec={() => runSpec(app, v)} />
            <LiveStatus
              running={running} paused={paused} updatedAt={summary.dataUpdatedAt}
              onPause={() => setPaused(true)} onResume={() => setPaused(false)} onRefresh={() => void refresh()}
            />
          </RunHeaderActions>
        )}
      />
      <AttentionStrip status={scopedStatus} from={onTabSearch(search, "runs")} onFollow={() => setFollowed((n) => n + 1)} />
      <JobTabs tab={tab} onTab={setTab} />
      <div role="tabpanel" id={JOB_PANEL_ID} aria-labelledby={jobTabId(tab)} className="job-panel">
        {/* A followed part rewrites the Runs tab's filters: it re-reads the URL. */}
        <Panel
          key={followed}
          tab={tab} ws={ws} app={app} v={v} name={head.name ?? undefined} detail={detail} summary={data}
          live={{ paused, onPaused: setPaused, refresh }}
        />
      </div>
      <JobCliCard ws={ws} app={app} verstr={v} />
    </div>
  );
}
