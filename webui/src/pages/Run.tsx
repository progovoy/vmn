import { Fragment, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, appName as toAppName } from "../api";
import type { ExperimentDetail, MetricsSchema } from "../types";
import {
  fmtDuration, fmtVal, metricGoal, pollIntervalMs, relTime,
} from "../util";
import { JobCard, Skeleton, useJob } from "../components/ui";
import { usePolling } from "../hooks/usePolling";
import ArtifactsList from "../components/ArtifactsList";
import StatusPill from "../components/StatusPill";
import RunLog from "../components/RunLog";
import TrainingCurves from "../components/TrainingCurves";

/** Inline `vmn experiment add -v <verstr> --metrics …` — append more metric
 *  points to this run. Latest value wins in the summary; every point is kept
 *  for the training-curve chart. */
function AppendMetrics({ ws, app, appName, verstr, onAdded }: {
  ws: string; app: string; appName: string; verstr: string; onAdded: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const { job, error, run } = useJob((j) => {
    if (j.status === "succeeded") {
      setText("");
      setOpen(false);
      onAdded();
    }
  });

  const submit = () => {
    const metrics: Record<string, string> = {};
    for (const pair of text.trim().split(/\s+/).filter(Boolean)) {
      const eq = pair.indexOf("=");
      if (eq < 1) {
        setParseError(`"${pair}" is not key=value`);
        return;
      }
      metrics[pair.slice(0, eq)] = pair.slice(eq + 1);
    }
    if (Object.keys(metrics).length === 0) {
      setParseError("enter at least one key=value");
      return;
    }
    setParseError(null);
    run(ws, app, "exp_add", { verstr, metrics });
  };

  if (!open) {
    return (
      <button
        className="link"
        style={{ marginTop: 12 }}
        onClick={() => setOpen(true)}
      >
        ＋ append metrics
      </button>
    );
  }

  const running = job?.status === "running";
  const cli =
    `vmn exp add ${appName} -v ${verstr}` +
    (text.trim() ? ` --metrics ${text.trim()}` : "");
  return (
    <div style={{ marginTop: 12, borderTop: "1px solid var(--line)", paddingTop: 12 }}>
      <label className="field">
        add metrics (key=value, space-separated)
        <input
          className="mono"
          placeholder="loss=0.09 acc=0.95"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          autoFocus
        />
      </label>
      <div className="toolbar" style={{ marginTop: 10, marginBottom: 0 }}>
        <button className="primary" onClick={submit} disabled={running}>
          {running ? "Adding…" : "Append"}
        </button>
        <button onClick={() => { setOpen(false); setParseError(null); }}>Cancel</button>
        {(parseError || error) && <span className="error">{parseError || error}</span>}
      </div>
      <div className="cli-hint">{cli}</div>
      {job && job.status === "failed" && <JobCard job={job} />}
    </div>
  );
}

/** Params card: the verbatim `params` (strings and booleans included), with
 *  snapshot `user_meta` only as a fallback for records that have no params. */
function ParamsCard({ params }: { params: Record<string, unknown> | null | undefined }) {
  if (!params || Object.keys(params).length === 0) return null;
  return (
    <div className="card">
      <div className="eyebrow">parameters</div>
      <div className="kv">
        {Object.entries(params).map(([k, v]) => (
          <Fragment key={k}>
            <div className="k">{k}</div>
            <div className="mono">{typeof v === "object" && v !== null ? JSON.stringify(v) : String(v)}</div>
          </Fragment>
        ))}
      </div>
    </div>
  );
}

export default function Run() {
  const { ws, app, verstr } = useParams() as {
    ws: string; app: string; verstr: string;
  };
  const [detail, setDetail] = useState<ExperimentDetail | null>(null);
  const [schema, setSchema] = useState<MetricsSchema | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);

  const load = useCallback(
    () => api.experiment(ws, app, verstr)
      .then(setDetail)
      .catch((e) => setError(String(e))),
    [ws, app, verstr]
  );
  useEffect(() => {
    load();
    api.metricsSchema(ws, app).then(setSchema).catch(() => setSchema({}));
  }, [load, ws, app]);
  // Follow a live run on its own, even with the Live toggle off. One cadence
  // either way — the payload only changes when the runner beats.
  const running = detail?.status?.status === "running";
  const pollMs = pollIntervalMs(detail?.status?.heartbeat_interval_sec);
  usePolling(load, pollMs, live || running);

  if (error) return <div className="error">{error}</div>;
  if (!detail) return <Skeleton />;

  const meta = detail.metadata;
  const st = detail.status;
  const appName = toAppName(app);
  const runUrl = (v: string) =>
    `/ws/${ws}/app/${app}/run/${encodeURIComponent(v)}`;
  const captured =
    Object.entries(detail.patches)
      .filter(([, v]) => v)
      .map(([k]) => k.replaceAll("_", " "))
      .join(", ") || "clean tree";
  const logTail = detail.log_tail ?? detail.log ?? [];
  const logTotal = detail.log_total ?? logTail.length;
  // `run` entries are written last, so the log tail carries them.
  const runSecs = logTail
    .filter((e) => e.type === "run")
    .reduce((s, e) => s + (Number(e.duration_sec) || 0), 0);

  return (
    <>
      <Link className="back-link" to={`/ws/${ws}/app/${app}`}>
        ← experiments
      </Link>
      <div className="page-head" style={{ alignItems: "center", marginBottom: 6 }}>
        <h1 className="mono" style={{ fontSize: 20 }}>{meta.verstr}</h1>
        {Boolean(meta.branch) && <span className="badge">{meta.branch as string}</span>}
        <button
          className={live ? "primary" : ""}
          onClick={() => setLive((v) => !v)}
          style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: "auto" }}
        >
          {live && <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--good)", animation: "pulse 1.5s infinite" }} />}
          {live ? "Live" : "Live"}
        </button>
      </div>
      {Boolean(meta.note) && (
        <p style={{ color: "var(--text-2)", margin: "0 0 20px" }}>
          {meta.note as string}
        </p>
      )}

      {st && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="eyebrow">status</div>
          <div className="status-head">
            <StatusPill
              status={st.status}
              exitCode={st.exit_code}
              durationSec={st.duration_sec}
              staleSec={st.stale_sec}
            />
            {st.status === "stuck" && st.stale_sec != null && (
              <span className="stale">
                ⚠ no heartbeat for {fmtDuration(st.stale_sec)}
              </span>
            )}
            {st.tree_status && st.tree_status !== st.status && (
              <span className="tree-roll">tree {st.tree_status}</span>
            )}
          </div>
          <div className="kv" style={{ marginTop: 12 }}>
            {st.exit_code !== null && (
              <><div className="k">exit code</div><div className="mono">{st.exit_code}</div></>
            )}
            <div className="k">duration</div>
            <div>{st.duration_sec !== null ? `${st.duration_sec}s` : "—"}</div>
            {st.pid !== null && (
              <><div className="k">pid</div><div className="mono">{st.pid}</div></>
            )}
            {Boolean(st.host) && (
              <><div className="k">host</div><div className="mono">{st.host}</div></>
            )}
            {Boolean(st.heartbeat) && (
              <>
                <div className="k">heartbeat</div>
                <div title={st.heartbeat ?? ""}>{relTime(st.heartbeat)}</div>
              </>
            )}
            {st.command && st.command.length > 0 && (
              <>
                <div className="k">command</div>
                <div className="mono">{st.command.join(" ")}</div>
              </>
            )}
            {Boolean(st.parent) && (
              <>
                <div className="k">parent</div>
                <div><Link className="mono" to={runUrl(st.parent!)}>{st.parent}</Link></div>
              </>
            )}
            {st.children.length > 0 && (
              <>
                <div className="k">children</div>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  {st.children.map((c) => (
                    <Link key={c} className="mono" to={runUrl(c)}>{c}</Link>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      <div className="card-grid-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <div className="eyebrow">metadata</div>
          <div className="kv">
            <div className="k">branch</div>
            <div className="mono">{meta.branch as string}</div>
            <div className="k">base</div>
            <div className="mono">
              {meta.base_version as string} ({(meta.base_commit as string)?.slice(0, 7)})
            </div>
            <div className="k">created</div>
            <div title={meta.timestamp as string}>{relTime(meta.timestamp as string)}</div>
            <div className="k">captured</div>
            <div style={{ color: "var(--text-2)" }}>{captured}</div>
            <div className="k">runtime</div>
            <div>{runSecs ? `${runSecs}s` : "—"}</div>
            {Boolean(meta.from_snapshot) && (
              <><div className="k">from snapshot</div><div className="mono">{String(meta.from_snapshot)}</div></>
            )}
            {Boolean(meta.code_verstr) && meta.code_verstr !== meta.verstr && (
              <><div className="k">code version</div><div className="mono">{String(meta.code_verstr)}</div></>
            )}
          </div>
        </div>
        <ParamsCard
          params={
            detail.params && Object.keys(detail.params).length > 0
              ? detail.params
              : (meta.user_meta as Record<string, unknown> | null | undefined)
          }
        />
        <div className="card">
          <div className="eyebrow">final metrics</div>
          {Object.keys(detail.metrics).length === 0 ? (
            <div className="empty" style={{ padding: 12 }}>No metrics logged.</div>
          ) : (
            <div>
              {Object.entries(detail.metrics).map(([k, v]) => {
                const goal = metricGoal(schema, k);
                const isPrimary = Boolean(schema?.[k]?.primary);
                return (
                  <div
                    key={k}
                    style={{
                      display: "flex", alignItems: "center",
                      justifyContent: "space-between", padding: "7px 0",
                      borderBottom: "1px solid var(--line)",
                    }}
                  >
                    <span style={{ color: "var(--text-2)", fontSize: 13 }}>
                      {k}{" "}
                      {typeof v === "number" && (
                        <span style={{ color: "var(--text-3)", fontSize: 11 }}>
                          {goal === "min" ? "↓" : "↑"}
                        </span>
                      )}
                    </span>
                    <span className={`metric${isPrimary ? " best" : ""}`}>
                      {fmtVal(v)}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
          <AppendMetrics ws={ws} app={app} appName={appName} verstr={meta.verstr as string} onAdded={load} />
        </div>
      </div>

      <TrainingCurves
        series={detail.series}
        seriesTotal={detail.series_total}
        startedAt={st?.started_at}
      />

      <div className="card-grid-wide">
        <RunLog ws={ws} app={app} verstr={meta.verstr as string} tail={logTail} total={logTotal} />
        <div className="card">
          <div className="eyebrow">reproduce</div>
          <div className="cli-hint">
            vmn exp restore {appName} -v {meta.verstr}
          </div>
          <div className="cli-hint">
            vmn exp export {appName} -v {meta.verstr}
          </div>
        </div>
      </div>
      {detail.artifacts && detail.artifacts.length > 0 && (
        <ArtifactsList
          artifacts={detail.artifacts}
          downloadUrl={(filename) =>
            `/api/v1/workspaces/${ws}/apps/${app}/experiments/${encodeURIComponent(meta.verstr as string)}/artifacts/${encodeURIComponent(filename)}`
          }
        />
      )}
    </>
  );
}
