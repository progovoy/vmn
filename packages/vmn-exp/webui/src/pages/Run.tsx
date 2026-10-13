import { useCallback, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { appName as toAppName, artifactUrl } from "../api";
import { fetchSeriesBatch, fetchSeriesRange } from "../apiSeries";
import { metricKeys, type MetricKeysQuery } from "../apiRun";
import { findCachedRow, rowsPrefix, runQuery, useMetricsSchema, useMeta } from "../queries";
import type { ExperimentDetail } from "../types";
import { pollIntervalMs, runHref } from "../util";
import { Skeleton } from "../components/ui";
import NotFound from "../components/shell/NotFound";
import { isMissingRun } from "../shell/notFoundCopy";
import { usePolling } from "../hooks/usePolling";
import ArtifactsList from "../components/ArtifactsList";
import RegisterModelDialog from "../components/RegisterModelDialog";
import AppendMetrics from "../components/AppendMetrics";
import LiveStatus from "../components/LiveStatus";
import NoteEditor from "../components/NoteEditor";
import Comments from "../components/Comments";
import ReportsUsing from "../components/ReportsUsing";
import { commentTarget } from "../apiReports";
import AddToReport from "../reports/AddToReport";
import { runSpec } from "../reports/viewSpecs";
import TagEditor from "../components/TagEditor";
import RunLog from "../components/RunLog";
import RunLineage from "../components/RunLineage";
import SimilarRuns from "../components/SimilarRuns";
import RunOutput, { OUTPUT_LOG } from "../components/RunOutput";
import RunErrorCard from "../components/RunErrorCard";
import TrainingCurves from "../components/TrainingCurves";
import RunChanges from "../components/RunChanges";
import { BASELINE_PARAM } from "../components/runChangesBaseline";
import SweepSection, { sweepSpecOf } from "../components/SweepSection";
import { FleetCard, MetadataCard, MetricsCard, StatusCard } from "./RunSections";
import RunCards from "./RunCards";
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

/** The Changes card, its baseline kept in `?baseline=` (a link like the
 *  failure card's "since last good" sets it with `changesSearch(ref)`). */
function RunChangesSection({ ws, app, verstr }: { ws: string; app: string; verstr: string }) {
  const [search, setSearch] = useSearchParams();
  const onBaseline = (ref: string) => setSearch((prev) => {
    const next = new URLSearchParams(prev);
    next.set(BASELINE_PARAM, ref);
    return next;
  }, { replace: true });
  return (
    <RunChanges ws={ws} app={app} verstr={verstr}
      baseline={search.get(BASELINE_PARAM)} onBaseline={onBaseline} />
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
  const fetchRange = useCallback(
    (metric: string, lo: number, hi: number) =>
      fetchSeriesRange(ws, app, verstr, metric, lo, hi, RUN_POINTS),
    [ws, app, verstr],
  );
  const fetchKeys = useCallback(
    (q: MetricKeysQuery) => metricKeys(ws, app, verstr, q), [ws, app, verstr],
  );
  const logTail = detail.log_tail ?? detail.log ?? [];
  const logTotal = detail.log_total ?? logTail.length;
  return (
    <>
      <TrainingCurves
        series={detail.series} seriesTotal={detail.series_total} startedAt={detail.status?.started_at}
        stepMetrics={detail.step_metrics} fetchJoined={fetchJoined}
        fetchRange={fetchRange} fetchKeys={fetchKeys}
        markStep={detail.forked_from?.step} hiddenMetrics={detail.hidden_metrics}
      />
      <RunChangesSection ws={ws} app={app} verstr={verstr} />
      <RunMediaSection ws={ws} app={app} detail={detail} />
      <div className="card-grid-wide">
        <RunLog ws={ws} app={app} verstr={verstr} tail={logTail} total={logTotal} />
        <div className="card">
          <h2 className="section-title">Reproduce</h2>
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
      <SimilarRuns ws={ws} app={app} verstr={verstr} />
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
  const [paused, setPaused] = useState(false);
  const detail = query.data;

  // Follow a running run on its own until paused, at the cadence its
  // heartbeat can move the payload at; anything else refreshes on demand.
  const running = detail?.status?.status === "running";
  const pollMs = pollIntervalMs(detail?.status?.heartbeat_interval_sec);
  usePolling(() => query.refetch(), pollMs, running && !paused);

  if (query.error && !detail) {
    if (isMissingRun(query.error)) return <NotFound kind="run" ws={ws} appTag={app} runRef={verstr} />;
    return <div className="error">{String(query.error)}</div>;
  }
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
        <LiveStatus
          running={running} paused={paused} updatedAt={query.dataUpdatedAt}
          onPause={() => setPaused(true)} onResume={() => setPaused(false)}
          onRefresh={() => query.refetch()}
        />
      </div>
      {detail && (
        <ForkOrigin forkedFrom={detail.forked_from} rerunOf={detail.rerun_of} rewinds={detail.rewinds} runUrl={runUrl} />
      )}
      <NoteEditor key={summary.verstr} ws={ws} app={app} verstr={summary.verstr} note={summary.note} />
      <TagEditor key={`tags-${summary.verstr}`} ws={ws} app={app} verstr={summary.verstr} tags={summary.tags} />

      {summary.status && <StatusCard st={summary.status} runUrl={runUrl} />}
      {summary.status && (
        <RunErrorCard status={summary.status}
          hasOutputLog={!!detail?.artifacts?.some((a) => a.name === OUTPUT_LOG)} />
      )}
      {summary.status?.fleet && <FleetCard fleet={summary.status.fleet} runUrl={runUrl} />}
      {sweepSpec && (
        <SweepSection ws={ws} app={app} verstr={summary.verstr} runUrl={runUrl} />
      )}

      <RunCards
        metadata={detail ? <MetadataCard detail={detail} /> : <Skeleton />}
        params={summary.params}
        metrics={(
          <MetricsCard metrics={summary.metrics} summary={summary.metricSummary} schema={schema}>
            {detail && (
              <AppendMetrics key={summary.verstr} ws={ws} app={app} appName={appName} verstr={summary.verstr} onAdded={onMetricsAdded} />
            )}
          </MetricsCard>
        )}
      />

      {detail ? <RunBody ws={ws} app={app} appName={appName} detail={detail} /> : <Skeleton />}
      <ReportsUsing ws={ws} app={appName} verstr={summary.verstr} />
      <aside className="card run-comments" aria-label="Comments">
        <h2 className="section-title">Comments</h2>
        <Comments ws={ws} target={commentTarget.run(appName, summary.verstr)} />
      </aside>
    </>
  );
}
