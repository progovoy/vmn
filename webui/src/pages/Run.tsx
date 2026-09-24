import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { appName as toAppName } from "../api";
import { useAppQueryClient } from "../queryClient";
import { findCachedRow, rowsPrefix, runQuery, useMetricsSchema } from "../queries";
import type { ExperimentDetail } from "../types";
import { pollIntervalMs, runHref } from "../util";
import { Skeleton } from "../components/ui";
import { usePolling } from "../hooks/usePolling";
import ArtifactsList from "../components/ArtifactsList";
import AppendMetrics from "../components/AppendMetrics";
import LiveToggle from "../components/LiveToggle";
import NoteEditor from "../components/NoteEditor";
import RunLog from "../components/RunLog";
import TrainingCurves from "../components/TrainingCurves";
import { MetadataCard, MetricsCard, ParamsCard, StatusCard } from "./RunSections";
import { summaryFromDetail, summaryFromRow } from "./runSummary";

function RunBody({ ws, app, appName, detail }: {
  ws: string; app: string; appName: string; detail: ExperimentDetail;
}) {
  const verstr = detail.metadata.verstr;
  const logTail = detail.log_tail ?? detail.log ?? [];
  const logTotal = detail.log_total ?? logTail.length;
  return (
    <>
      <TrainingCurves series={detail.series} seriesTotal={detail.series_total} startedAt={detail.status?.started_at} />
      <div className="card-grid-wide">
        <RunLog ws={ws} app={app} verstr={verstr} tail={logTail} total={logTotal} />
        <div className="card">
          <div className="eyebrow">reproduce</div>
          <div className="cli-hint">vmn exp restore {appName} -v {verstr}</div>
          <div className="cli-hint">vmn exp export {appName} -v {verstr}</div>
        </div>
      </div>
      {detail.artifacts && detail.artifacts.length > 0 && (
        <ArtifactsList
          artifacts={detail.artifacts}
          downloadUrl={(filename) =>
            `/api/v1/workspaces/${ws}/apps/${app}/experiments/${encodeURIComponent(verstr)}/artifacts/${encodeURIComponent(filename)}`
          }
        />
      )}
    </>
  );
}

export default function Run() {
  const { ws, app, verstr } = useParams() as { ws: string; app: string; verstr: string };
  const client = useAppQueryClient();
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

  return (
    <>
      <Link className="back-link" to={`/ws/${ws}/app/${app}`}>← experiments</Link>
      <div className="page-head" style={{ alignItems: "center", marginBottom: 6 }}>
        <h1 className="mono" style={{ fontSize: 20 }}>{summary.verstr}</h1>
        {summary.branch && <span className="badge">{summary.branch}</span>}
        <LiveToggle live={live} onToggle={() => setLive((v) => !v)} style={{ marginLeft: "auto" }} />
      </div>
      <NoteEditor key={summary.verstr} ws={ws} app={app} verstr={summary.verstr} note={summary.note} />

      {summary.status && <StatusCard st={summary.status} runUrl={runUrl} />}

      <div className="card-grid-2" style={{ marginBottom: 16 }}>
        {detail ? <MetadataCard detail={detail} /> : <Skeleton />}
        <ParamsCard params={summary.params} />
        <MetricsCard metrics={summary.metrics} schema={schema}>
          {detail && (
            <AppendMetrics key={summary.verstr} ws={ws} app={app} appName={appName} verstr={summary.verstr} onAdded={onMetricsAdded} />
          )}
        </MetricsCard>
      </div>

      {detail ? <RunBody ws={ws} app={app} appName={appName} detail={detail} /> : <Skeleton />}
    </>
  );
}
