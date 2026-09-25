import { Fragment, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ExperimentDetail, Fleet, MetricsSchema, RunStatus } from "../types";
import { fmtDuration, fmtVal, metricGoal, relTime } from "../util";
import StatusPill from "../components/StatusPill";

/** A duration on the relTime ladder (2h), with the exact seconds beside it. */
export function Duration({ secs }: { secs: number | null | undefined }) {
  if (secs == null) return <div>—</div>;
  const text = fmtDuration(secs);
  const exact = `${Math.round(secs)}s`;
  return (
    <div>
      <span>{text}</span>
      {exact !== text && <>{" "}<span className="exact-secs">{exact}</span></>}
    </div>
  );
}

export function StatusCard({ st, runUrl }: { st: RunStatus; runUrl: (v: string) => string }) {
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="eyebrow">status</div>
      <div className="status-head">
        <StatusPill status={st.status} exitCode={st.exit_code} durationSec={st.duration_sec} staleSec={st.stale_sec} />
        {st.status === "stuck" && st.stale_sec != null && (
          <span className="stale">⚠ no heartbeat for {fmtDuration(st.stale_sec)}</span>
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
        <Duration secs={st.duration_sec} />
        {st.pid !== null && <><div className="k">pid</div><div className="mono">{st.pid}</div></>}
        {Boolean(st.host) && <><div className="k">host</div><div className="mono">{st.host}</div></>}
        {Boolean(st.heartbeat) && (
          <><div className="k">heartbeat</div><div title={st.heartbeat ?? ""}>{relTime(st.heartbeat)}</div></>
        )}
        {st.command && st.command.length > 0 && (
          <><div className="k">command</div><div className="mono">{st.command.join(" ")}</div></>
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
              {st.children.map((c) => <Link key={c} className="mono" to={runUrl(c)}>{c}</Link>)}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** Params card: the verbatim `params` (strings and booleans included), with
 *  snapshot `user_meta` only as a fallback for records that have no params. */
export function ParamsCard({ params }: { params: Record<string, unknown> | null | undefined }) {
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

export function MetricsCard({ metrics, schema, children }: {
  metrics: ExperimentDetail["metrics"]; schema: MetricsSchema | null; children?: ReactNode;
}) {
  return (
    <div className="card">
      <div className="eyebrow">final metrics</div>
      {Object.keys(metrics).length === 0 ? (
        <div className="empty" style={{ padding: 12 }}>No metrics logged.</div>
      ) : (
        <div>
          {Object.entries(metrics).map(([k, v]) => (
            <div key={k} className="metric-line">
              <span className="metric-name">
                {k}{" "}
                {typeof v === "number" && (
                  <span className="metric-goal">{metricGoal(schema, k) === "min" ? "↓" : "↑"}</span>
                )}
              </span>
              <span className={`metric${schema?.[k]?.primary ? " best" : ""}`}>{fmtVal(v)}</span>
            </div>
          ))}
        </div>
      )}
      {children}
    </div>
  );
}

const STATUS_COLORS: Record<string, string> = {
  running: "var(--accent)",
  succeeded: "var(--good)",
  failed: "var(--bad)",
  stuck: "var(--hotfix)",
  created: "var(--text-3)",
  waiting: "var(--text-3)",
};

const COLLAPSE_THRESHOLD = 10;

export function FleetCard({ fleet, runUrl }: { fleet: Fleet; runUrl: (v: string) => string }) {
  const [expanded, setExpanded] = useState(false);
  const nonZeroCounts = Object.entries(fleet.counts).filter(([, n]) => n > 0);
  const visibleChildren = expanded || fleet.children.length <= COLLAPSE_THRESHOLD
    ? fleet.children
    : fleet.children.slice(0, COLLAPSE_THRESHOLD);

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="eyebrow">fleet</div>
      <div className="fleet-summary">
        {nonZeroCounts.map(([status, count]) => (
          <span key={status} className="fleet-count">
            <span className="dot" style={{ background: STATUS_COLORS[status] ?? "var(--text-3)" }} />
            <span>{count}</span>
            <span style={{ color: "var(--text-2)" }}>{status}</span>
          </span>
        ))}
      </div>
      <div className="fleet-bar">
        {nonZeroCounts.map(([status, count]) => (
          <div
            key={status}
            className="segment"
            style={{
              width: `${(count / fleet.expected) * 100}%`,
              background: STATUS_COLORS[status] ?? "var(--text-3)",
            }}
          />
        ))}
      </div>
      <div className="fleet-children">
        <table>
          <thead>
            <tr>
              <th>run</th>
              <th>status</th>
              <th>progress</th>
            </tr>
          </thead>
          <tbody>
            {visibleChildren.map((child) => (
              <tr key={child.verstr}>
                <td>
                  <Link className="mono" to={runUrl(child.verstr)}>{child.verstr}</Link>
                </td>
                <td>
                  <StatusPill status={child.status} />
                </td>
                <td>
                  {child.progress != null && child.progress_total != null ? (
                    <span className="progress-bar">
                      <span>{child.progress} / {child.progress_total}</span>
                      <span className="progress-track">
                        <span
                          className="progress-fill"
                          style={{ width: `${(child.progress / child.progress_total) * 100}%` }}
                        />
                      </span>
                    </span>
                  ) : (
                    <span style={{ color: "var(--text-3)" }}>{"—"}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {fleet.children.length > COLLAPSE_THRESHOLD && !expanded && (
          <button
            className="link"
            style={{ marginTop: 8 }}
            onClick={() => setExpanded(true)}
            aria-label={`Show all ${fleet.children.length} children`}
          >
            Show all {fleet.children.length}
          </button>
        )}
      </div>
    </div>
  );
}

export function MetadataCard({ detail }: { detail: ExperimentDetail }) {
  const meta = detail.metadata;
  const captured = Object.entries(detail.patches)
    .filter(([, v]) => v).map(([k]) => k.replaceAll("_", " ")).join(", ") || "clean tree";
  const logTail = detail.log_tail ?? detail.log ?? [];
  // `run` entries are written last, so the log tail carries them.
  const runSecs = logTail.filter((e) => e.type === "run")
    .reduce((s, e) => s + (Number(e.duration_sec) || 0), 0);
  return (
    <div className="card">
      <div className="eyebrow">metadata</div>
      <div className="kv">
        <div className="k">branch</div>
        <div className="mono">{meta.branch as string}</div>
        <div className="k">base</div>
        <div className="mono">{meta.base_version as string} ({(meta.base_commit as string)?.slice(0, 7)})</div>
        <div className="k">created</div>
        <div title={meta.timestamp as string}>{relTime(meta.timestamp as string)}</div>
        <div className="k">captured</div>
        <div style={{ color: "var(--text-2)" }}>{captured}</div>
        <div className="k">runtime</div>
        <Duration secs={runSecs || null} />
        {Boolean(meta.from_snapshot) && (
          <><div className="k">from snapshot</div><div className="mono">{String(meta.from_snapshot)}</div></>
        )}
        {Boolean(meta.code_verstr) && meta.code_verstr !== meta.verstr && (
          <><div className="k">code version</div><div className="mono">{String(meta.code_verstr)}</div></>
        )}
      </div>
    </div>
  );
}
