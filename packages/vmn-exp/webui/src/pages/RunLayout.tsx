import { useCallback, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { artifactUrl } from "../api";
import { fetchSeriesBatch, fetchSeriesRange } from "../apiSeries";
import { metricKeys, type MetricKeysQuery } from "../apiRun";
import { useMeta } from "../queries";
import type { ExperimentDetail, RunStatus } from "../types";
import ArtifactsList from "../components/ArtifactsList";
import RegisterModelDialog from "../components/RegisterModelDialog";
import ReportsUsing from "../components/ReportsUsing";
import RunLineage from "../components/RunLineage";
import RunLog from "../components/RunLog";
import RunOutput from "../components/RunOutput";
import RunChanges from "../components/RunChanges";
import SimilarRuns from "../components/SimilarRuns";
import TrainingCurves from "../components/TrainingCurves";
import { BASELINE_PARAM } from "../components/runChangesBaseline";
import { RunComments, RunEnvironment, StatusDetails } from "./RunDetails";
import RunMediaSection from "./RunMedia";
import "./runLayout.css";

/** The run page in the order it answers questions (plan 20 D5): what it is,
 *  how it went, what changed, then the details, collapsed. */
export default function RunLayout(s: {
  head: ReactNode;
  /** An inner run's job context bar (plan 23 W7), under the header. */
  context?: ReactNode;
  notes: ReactNode; failure: ReactNode; curves: ReactNode; changes: ReactNode;
  fleet: ReactNode; cards: ReactNode; related: ReactNode; outputs: ReactNode; details: ReactNode;
}) {
  return (
    <>
      {s.head}{s.context}{s.notes}{s.failure}{s.curves}{s.changes}{s.fleet}
      {s.cards}{s.related}{s.outputs}{s.details}
    </>
  );
}

/** Points per joined metric, as many as the detail's own series carry. */
const RUN_POINTS = 2000;

/** Training curves (D5 4), its zoom/join/keys fetchers bound to this run. */
export function RunCurves({ ws, app, detail }: { ws: string; app: string; detail: ExperimentDetail }) {
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
  return (
    <TrainingCurves
      series={detail.series} seriesTotal={detail.series_total} startedAt={detail.status?.started_at}
      stepMetrics={detail.step_metrics} fetchJoined={fetchJoined}
      fetchRange={fetchRange} fetchKeys={fetchKeys}
      markStep={detail.forked_from?.step} hiddenMetrics={detail.hidden_metrics}
      ranges={detail.ranges} rangesTotal={detail.ranges_total}
    />
  );
}

/** The Changes card (D5 5), its baseline kept in `?baseline=` (a link like
 *  the failure card's "since last good" sets it with `changesSearch(ref)`). */
export function RunChangesSection({ ws, app, verstr }: { ws: string; app: string; verstr: string }) {
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

/** Similar runs | Lineage (D5 8). */
export function RunRelated({ ws, app, verstr }: { ws: string; app: string; verstr: string }) {
  return (
    <div className="run-pair">
      <SimilarRuns ws={ws} app={app} verstr={verstr} />
      <RunLineage ws={ws} app={app} verstr={verstr} />
    </div>
  );
}

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

/** What the run produced: its output log, artifacts (registrable as a
 *  model) and the reports that show it. */
export function RunOutputs({ ws, app, appName, detail }: {
  ws: string; app: string; appName: string; detail: ExperimentDetail;
}) {
  const verstr = detail.metadata.verstr;
  const downloadUrl = (filename: string) => artifactUrl(ws, app, verstr, filename);
  return (
    <>
      {detail.artifacts && detail.artifacts.length > 0 && (
        <>
          <RunOutput artifacts={detail.artifacts} downloadUrl={downloadUrl} />
          <ArtifactsList artifacts={detail.artifacts} downloadUrl={downloadUrl} />
          <RegisterModelButton ws={ws} app={appName} verstr={verstr} />
        </>
      )}
      <ReportsUsing ws={ws} app={appName} verstr={verstr} />
    </>
  );
}

/** The collapsed details (D5 9): Status details, Log, Environment, Media
 *  (open when present), Comments (open when there are any). */
export function RunDetailSections({ ws, app, appName, verstr, status, detail, runUrl }: {
  ws: string; app: string; appName: string; verstr: string;
  status: RunStatus | null; detail: ExperimentDetail | undefined; runUrl: (v: string) => string;
}) {
  const logTail = detail ? detail.log_tail ?? detail.log ?? [] : [];
  return (
    <>
      <StatusDetails status={status} detail={detail} runUrl={runUrl} />
      {detail && (
        <>
          <RunLog ws={ws} app={app} verstr={verstr} tail={logTail} total={detail.log_total ?? logTail.length} />
          <RunEnvironment detail={detail} />
          <RunMediaSection ws={ws} app={app} detail={detail} />
        </>
      )}
      <RunComments ws={ws} app={appName} verstr={verstr} />
    </>
  );
}
