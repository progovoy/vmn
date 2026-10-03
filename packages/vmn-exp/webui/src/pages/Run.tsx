import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { appName as toAppName, artifactUrl } from "../api";
import { fetchSeriesBatch } from "../apiSeries";
import { findCachedRow, rowsPrefix, runQuery, useMetricsSchema, useMeta } from "../queries";
import type { ExperimentDetail } from "../types";
import { pollIntervalMs, runHref } from "../util";
import { Skeleton } from "../components/ui";
import { usePolling } from "../hooks/usePolling";
import ArtifactsList from "../components/ArtifactsList";
import RegisterModelDialog from "../components/RegisterModelDialog";
import AppendMetrics from "../components/AppendMetrics";
import LiveToggle from "../components/LiveToggle";
import NoteEditor from "../components/NoteEditor";
import Comments from "../components/Comments";
import ReportsUsing from "../components/ReportsUsing";
import { commentTarget } from "../apiReports";
import AddToReport from "../reports/AddToReport";
import { runSpec } from "../reports/viewSpecs";
import TagEditor from "../components/TagEditor";
import RunLog from "../components/RunLog";
import RunLineage from "../components/RunLineage";
import RunOutput from "../components/RunOutput";
import TrainingCurves from "../components/TrainingCurves";
import SweepSection, { sweepSpecOf } from "../components/SweepSection";
import { FleetCard, MetadataCard, MetricsCard, ParamsCard, StatusCard } from "./RunSections";
import RunMediaSection from "./RunMedia";
import RunProvenanceSection from "./RunProvenance";
import { ForkOrigin } from "./RunFork";
import { RerunHints } from "./RunRerun";
import { summaryFromDetail, summaryFromRow } from "./runSummary";

function RegisterModelButton({ ws, app, verstr }: { ws: string; app: string; verstr: string }) {
  const meta = useMeta().data;
  const [open, setOpen] = useState(false);
  if (meta?.read_only) return null;
  return (
    <>
      <button className="link" style={{ marginTop: 8 }} onClick={() => setOpen(true)}
        aria-label="Register as model">
        Register as model
      </button>
      {open && (
        <RegisterModelDialog ws={ws} app={app} verstr={verstr} onDone={() => setOpen(false)} />
      )}
    </>
  );
}

/** Points per joined metric, as many as the detail's own series carry. */
const RUN_POINTS = 2000;

function RunBody({ ws, app, appName, detail }: {
  ws: string; app: string; appName: string; detail: ExperimentDetail;
}) {
  const verstr = detail.metadata.verstr;
  const fetchJoined = useCallback(
    (x: Record<string, string>) => fetchSeriesBatch(ws, app, [verstr], Object.keys(x), RUN_POINTS, x)
      .then((b) => b.series[verstr] ?? {}),
    [ws, app, verstr],
  );
  const logTail = detail.log_tail ?? detail.log ?? [];
  const logTotal = detail.log_total ?? logTail.length;
  return (
    <>
      <TrainingCurves
        series={detail.series} seriesTotal={detail.series_total} startedAt={detail.status?.started_at}
        stepMetrics={detail.step_metrics} fetchJoined={fetchJoined}
        markStep={detail.forked_from?.step} hiddenMetrics={detail.hidden_metrics}
      />
      <RunMediaSection ws={ws} app={app} detail={detail} />
      <div className="card-grid-wide">
        <RunLog ws={ws} app={app} verstr={verstr} tail={logTail} total={logTotal} />
        <div className="card">
          <div className="eyebrow">reproduce</div>
          <div className="cli-hint">vmn-exp restore {appName} -v {verstr}</div>
          <div className="cli-hint">vmn-exp export {appName} -v {verstr}</div>
          <RerunHints boardBase={`/ws/${ws}/app/${app}`} appName={appName} verstr={verstr}
            command={detail.status?.command} />
        </div>
      </div>
      {detail.artifacts && detail.artifacts.length > 0 && (
        <>
          <RunOutput
            artifacts={detail.artifacts}
            downloadUrl={(filename) => artifactUrl(ws, app, verstr, filename)}
          />
          <ArtifactsList
            artifacts={detail.artifacts}
            downloadUrl={(filename) => artifactUrl(ws, app, verstr, filename)}
          />
          <RegisterModelButton ws={ws} app={appName} verstr={verstr} />
        </>
      )}
      <RunProvenanceSection
        env={detail.env}
        inputs={detail.inputs}
        importedFrom={detail.imported_from}
      />
      <RunLineage ws={ws} app={app} verstr={verstr} />
    </>
  );
}

export default function Run() {
  const { ws, app, verstr } = useParams() as { ws: string; app: string; verstr: string };
  const client = useQueryClient();
  // Structural sharing keeps every unchanged part of a polled detail (its
  // series above all) the same object, so the charts don't redraw.
  const query = useQuery(runQuery(ws, app, verstr), client);
  const schema = useMetricsSchema(ws, app);
  const [live, setLive] = useState(false);
  const detail = query.data;

  // Follow a live run on its own, even with the Live toggle off. One cadence
  // either way — the payload only changes when the runner beats.
  const running = detail?.status?.status === "running";
  const pollMs = pollIntervalMs(detail?.status?.heartbeat_interval_sec);
  usePolling(() => query.refetch(), pollMs, live || running);

  if (query.error && !detail) return <div className="error">{String(query.error)}</div>;
  // Until the detail lands, the leaderboard's row for this run paints the top.
  const row = detail ? undefined : findCachedRow(client, ws, app, verstr);
  const summary = detail ? summaryFromDetail(detail) : row ? summaryFromRow(row) : null;
  if (!summary) return <Skeleton />;

  const appName = toAppName(app);
  // New metric points change this run's row in every cached list too.
  const onMetricsAdded = () => {
    query.refetch();
    client.invalidateQueries({ queryKey: rowsPrefix(ws, app) });
  };
  const runUrl = (v: string) => runHref(`/ws/${ws}/app/${app}`, v);
  const sweepSpec = detail ? sweepSpecOf(detail.metadata) : null;

  return (
    <>
      <Link className="back-link" to={`/ws/${ws}/app/${app}`}>← experiments</Link>
      <div className="page-head" style={{ alignItems: "center", marginBottom: 6 }}>
        <h1 className={summary.name ? undefined : "mono"} style={{ fontSize: 20 }}>
          {summary.name || summary.verstr}
        </h1>
        {summary.name && <span className="mono run-verstr">{summary.verstr}</span>}
        {summary.branch && <span className="badge">{summary.branch}</span>}
        <span style={{ marginLeft: "auto" }}><AddToReport ws={ws} spec={() => runSpec(app, summary.verstr)} /></span>
        <LiveToggle live={live} onToggle={() => setLive((v) => !v)} />
      </div>
      {detail && (
        <ForkOrigin forkedFrom={detail.forked_from} rerunOf={detail.rerun_of} rewinds={detail.rewinds} runUrl={runUrl} />
      )}
      <NoteEditor key={summary.verstr} ws={ws} app={app} verstr={summary.verstr} note={summary.note} />
      <TagEditor key={`tags-${summary.verstr}`} ws={ws} app={app} verstr={summary.verstr} tags={summary.tags} />

      {summary.status && <StatusCard st={summary.status} runUrl={runUrl} />}
      {summary.status?.fleet && <FleetCard fleet={summary.status.fleet} runUrl={runUrl} />}
      {sweepSpec && (
        <SweepSection ws={ws} app={app} verstr={summary.verstr} runUrl={runUrl} />
      )}

      <div className="card-grid-2" style={{ marginBottom: 16 }}>
        {detail ? <MetadataCard detail={detail} /> : <Skeleton />}
        <ParamsCard params={summary.params} />
        <MetricsCard metrics={summary.metrics} summary={summary.metricSummary} schema={schema}>
          {detail && (
            <AppendMetrics key={summary.verstr} ws={ws} app={app} appName={appName} verstr={summary.verstr} onAdded={onMetricsAdded} />
          )}
        </MetricsCard>
      </div>

      {detail ? <RunBody ws={ws} app={app} appName={appName} detail={detail} /> : <Skeleton />}
      <ReportsUsing ws={ws} app={appName} verstr={summary.verstr} />
      <aside className="card run-comments" aria-label="Comments">
        <div className="eyebrow">Comments</div>
        <Comments ws={ws} target={commentTarget.run(appName, summary.verstr)} />
      </aside>
    </>
  );
}
