import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { appName as toAppName } from "../api";
import { cachedRows, findCachedRow, rowsPrefix, runQuery, useMetricsSchema } from "../queries";
import type { ExperimentDetail } from "../types";
import { pollIntervalMs, runHref } from "../util";
import { isParamOnly } from "../util/paramKeys";
import { Skeleton } from "../components/ui";
import NotFound from "../components/shell/NotFound";
import { isMissingRun } from "../shell/notFoundCopy";
import { usePolling } from "../hooks/usePolling";
import { useLiveScope } from "../hooks/useLiveScope";
import AppendMetrics from "../components/AppendMetrics";
import LiveStatus from "../components/LiveStatus";
import NoteEditor from "../components/NoteEditor";
import AddToReport from "../reports/AddToReport";
import RunHeaderActions from "../components/RunHeaderActions";
import { runSpec } from "../reports/viewSpecs";
import TagEditor from "../components/TagEditor";
import { OUTPUT_LOG } from "../components/RunOutput";
import RunErrorCard from "../components/RunErrorCard";
import JobContextBar from "../components/JobContextBar";
import SweepSection, { sweepSpecOf } from "../components/SweepSection";
import { fleetIdxOf } from "../components/fleetRows";
import { FleetCard, MetricsCard } from "./RunSections";
import RunCards from "./RunCards";
import RunHead from "./RunHead";
import RunLayout, { RunChangesSection, RunCurves, RunDetailSections, RunOutputs, RunRelated } from "./RunLayout";
import { ForkOrigin } from "./RunFork";
import { paramsVariedFirst } from "./runParams";
import { summaryFromDetail, summaryFromRow } from "./runSummary";
import { sweepIncompleteLabel } from "../util/sweepProgress";
import JobPage from "./Job/JobPage";
import { jobSummaryQuery } from "./Job/jobQueries";

/** The metrics the Metrics card lists: params folded into `metrics` stay
 *  under Params (D2). */
function shownMetrics(metrics: ExperimentDetail["metrics"], detail: ExperimentDetail | undefined) {
  if (!detail) return metrics;
  const keys = Object.keys(metrics).filter((k) => !isParamOnly(k, detail));
  return keys.length === Object.keys(metrics).length ? metrics : Object.fromEntries(keys.map((k) => [k, metrics[k]]));
}

/** A run with children opens the job page (plan 23 W2) once its summary
 *  lands; a single or inner run, or a server without the summary endpoint
 *  (any error before one landed, a 404 above all), the run page. */
export default function Run() {
  const { ws, app, verstr } = useParams() as { ws: string; app: string; verstr: string };
  const client = useQueryClient();
  const query = useQuery(runQuery(ws, app, verstr), client);
  const detail = query.data;
  const st = detail?.status;
  const isJob = !!st && (st.kind === "outer" || !!st.fleet);
  const summary = useQuery({ ...jobSummaryQuery(ws, app, detail?.metadata.verstr ?? ""), enabled: isJob }, client);
  if (detail && isJob && (summary.data || summary.isPending)) {
    return <JobPage ws={ws} app={app} detail={detail} summary={summary} refetchDetail={() => query.refetch()} />;
  }
  return <SingleRun />;
}

function SingleRun() {
  const { ws, app, verstr } = useParams() as { ws: string; app: string; verstr: string };
  const client = useQueryClient();
  // Structural sharing keeps every unchanged part of a polled detail (its
  // series above all) the same object, so the charts don't redraw.
  const query = useQuery(runQuery(ws, app, verstr), client);
  const schema = useMetricsSchema(ws, app);
  const [paused, setPaused] = useState(false);
  const detail = query.data;

  // Follow a running run on its own until paused: pushed by its subtree's
  // live events, else polled at the cadence its heartbeat can move the
  // payload at; anything else refreshes on demand.
  const running = detail?.status?.status === "running";
  const live = useLiveScope({
    ws, app, scope: detail?.metadata.verstr, enabled: running && !paused,
    onChange: () => query.refetch(),
  });
  const pollMs = pollIntervalMs(detail?.status?.heartbeat_interval_sec);
  usePolling(() => query.refetch(), pollMs, running && !paused && !live.connected);

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
  const st = summary.status;

  return (
    <RunLayout
      head={(
        <RunHead ws={ws} app={app} summary={summary} importedFrom={detail?.imported_from} runUrl={runUrl}
          actions={(
            <RunHeaderActions ws={ws} app={app} verstr={summary.verstr} command={detail?.status?.command}>
              <AddToReport ws={ws} spec={() => runSpec(app, summary.verstr)} />
              <LiveStatus
                running={running} paused={paused} updatedAt={query.dataUpdatedAt}
                onPause={() => setPaused(true)} onResume={() => setPaused(false)}
                onRefresh={() => query.refetch()}
              />
            </RunHeaderActions>
          )} />
      )}
      context={st?.parent && (
        <JobContextBar ws={ws} app={app} verstr={summary.verstr} idx={summary.idx ?? null} job={st.parent} metrics={summary.metrics} />
      )}
      notes={(
        <>
          {detail && (
            <ForkOrigin forkedFrom={detail.forked_from} rerunOf={detail.rerun_of} rewinds={detail.rewinds} runUrl={runUrl} />
          )}
          <NoteEditor key={summary.verstr} ws={ws} app={app} verstr={summary.verstr} note={summary.note} />
          <TagEditor key={`tags-${summary.verstr}`} ws={ws} app={app} verstr={summary.verstr} tags={summary.tags} />
        </>
      )}
      failure={st && (
        <RunErrorCard status={st} context={detail} runPath={runUrl(summary.verstr)}
          hasOutputLog={!!detail?.artifacts?.some((a) => a.name === OUTPUT_LOG)} />
      )}
      curves={detail ? <RunCurves ws={ws} app={app} detail={detail} /> : <Skeleton />}
      changes={detail && <RunChangesSection ws={ws} app={app} verstr={summary.verstr} />}
      fleet={(
        <>
          {st?.fleet && <FleetCard
            fleet={st.fleet} schema={schema} runUrl={runUrl} table={!sweepSpec}
            incomplete={sweepIncompleteLabel(st)}
          />}
          {sweepSpec && (
            <SweepSection ws={ws} app={app} verstr={summary.verstr} runUrl={runUrl} idxOf={fleetIdxOf(st?.fleet)} />
          )}
        </>
      )}
      cards={(
        <RunCards
          params={paramsVariedFirst(summary.params, cachedRows(client, ws, app))}
          metrics={(
            <MetricsCard metrics={shownMetrics(summary.metrics, detail)} summary={summary.metricSummary} schema={schema}>
              {detail && (
                <AppendMetrics key={summary.verstr} ws={ws} app={app} appName={appName} verstr={summary.verstr} onAdded={onMetricsAdded} />
              )}
            </MetricsCard>
          )}
        />
      )}
      related={detail && <RunRelated ws={ws} app={app} verstr={summary.verstr} />}
      outputs={detail && <RunOutputs ws={ws} app={app} appName={appName} detail={detail} />}
      details={(
        <RunDetailSections ws={ws} app={app} appName={appName} verstr={summary.verstr}
          status={st} detail={detail} runUrl={runUrl} />
      )}
    />
  );
}
