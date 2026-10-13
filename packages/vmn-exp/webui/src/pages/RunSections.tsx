import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ExperimentDetail, Fleet, MetricSummary, MetricsSchema, RunState, RunStatus } from "../types";
import { fmtDuration, fmtVal, metricGoal, relTime } from "../util";
import StatusPill from "../components/StatusPill";
import FleetTable from "../components/FleetTable";
import { fleetMetric, fleetRowsOf, varyingParams } from "../components/fleetRows";

/** A single duration text (rounded seconds for short, ladder for longer),
 *  with the exact seconds in the title attribute. 0s shows as "<1s". */
export function Duration({ secs }: { secs: number | null | undefined }) {
  if (secs == null) return <div>—</div>;
  const rounded = Math.round(secs);
  const display = rounded === 0 ? "<1s" : secs < 60 ? `${rounded}s` : fmtDuration(secs);
  return (
    <div title={`${rounded}s`}>
      <span>{display}</span>
    </div>
  );
}

export function StatusCard({ st, runUrl }: { st: RunStatus; runUrl: (v: string) => string }) {
  // For outers, tree_status is the headline; the run's own status is secondary.
  const isOuter = st.kind === "outer" && st.tree_status;
  const primaryStatus = isOuter ? st.tree_status as RunState : st.status;
  const showOwnStatus = isOuter && (
    st.status === "failed" || st.status === "stuck"
    || (st.status === "running" && st.status !== st.tree_status)
  );
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <h2 className="section-title">Status</h2>
      <div className="status-head">
        <StatusPill status={primaryStatus} exitCode={st.exit_code} durationSec={st.duration_sec} staleSec={st.stale_sec} />
        {showOwnStatus && (
          <span className="tree-roll">own {st.status}</span>
        )}
        {st.status === "stuck" && st.stale_sec != null && (
          <span className="stale">⚠ no heartbeat for {fmtDuration(st.stale_sec)}</span>
        )}
        {!isOuter && st.tree_status && st.tree_status !== st.status && (
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
        {Boolean(st.heartbeat) && st.status !== "succeeded" && st.status !== "failed" && (
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
      </div>
    </div>
  );
}

/** Params card: the verbatim `params` (strings and booleans included). */
export function ParamsCard({ params }: { params: Record<string, unknown> | null | undefined }) {
  if (!params || Object.keys(params).length === 0) return null;
  return (
    <div className="card">
      <h2 className="section-title">Parameters</h2>
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

/** ["last 0.9", "min 0.2", "max 1", ...] — or null when all three read the same. */
function summaryPairs(parts: MetricSummary | undefined): string[] | null {
  if (!parts) return null;
  const shown = [parts.last, parts.min, parts.max].map(fmtVal);
  if (new Set(shown).size === 1) return null;
  const pairs = [`last ${shown[0]}`, `min ${shown[1]}`, `max ${shown[2]}`];
  if (parts.first != null) pairs.push(`first ${fmtVal(parts.first)}`);
  if (parts.mean != null) pairs.push(`mean ${fmtVal(parts.mean)}`);
  return pairs;
}

/** "last 0.9 · min 0.2 · max 1", wrapping only between whole pairs. */
function SummaryLine({ metric, pairs }: { metric: string; pairs: string[] }) {
  return (
    <span data-testid={`metric-summary-${metric}`} className="metric-summary">
      {pairs.map((p, i) => (
        <span key={p} className="metric-chunk">
          {i > 0 && <span className="metric-sep"> · </span>}
          <span className="metric-pair">{p}</span>
        </span>
      ))}
    </span>
  );
}

/** Each metric's summary value (its best, per the metric's policy), with
 *  last/min/max beside it when they differ. */
export function MetricsCard({ metrics, summary, schema, children }: {
  metrics: ExperimentDetail["metrics"];
  summary?: Record<string, MetricSummary>;
  schema: MetricsSchema | null;
  children?: ReactNode;
}) {
  return (
    <div className="card">
      <h2 className="section-title">Metrics</h2>
      {Object.keys(metrics).length === 0 ? (
        <div className="empty" style={{ padding: 12 }}>No metrics logged.</div>
      ) : (
        <div>
          {Object.entries(metrics).map(([k, v]) => {
            const pairs = summaryPairs(summary?.[k]);
            const goal = typeof v === "number" ? metricGoal(schema, k) : null;
            return (
              <div key={k} className="metric-line">
                <span className="metric-name">
                  {k}{" "}
                  {goal !== null && (
                    <span className="metric-goal">{goal === "min" ? "↓" : "↑"}</span>
                  )}
                </span>
                <span className="metric-values">
                  <span
                    data-testid={`metric-value-${k}`}
                    className={`metric${schema?.[k]?.primary ? " best" : ""}`}
                  >{fmtVal(v)}</span>
                  {pairs && <SummaryLine metric={k} pairs={pairs} />}
                </span>
              </div>
            );
          })}
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

const FLEET_DISPLAY_ORDER = ["waiting", "running", "succeeded", "failed", "stuck", "created"];

/** An outer run's children: status counts, a bar, and the fleet table —
 *  left out (`table={false}`) for a sweep, whose Sweep card lists them. */
export function FleetCard({ fleet, schema = null, runUrl, table = true }: {
  fleet: Fleet;
  schema?: MetricsSchema | null;
  runUrl: (v: string) => string;
  table?: boolean;
}) {
  const nonZeroCounts = FLEET_DISPLAY_ORDER
    .filter((s) => (fleet.counts[s] ?? 0) > 0)
    .map((s) => [s, fleet.counts[s]] as const);
  const metric = fleetMetric(fleet.children, schema);
  const rows = fleetRowsOf(fleet.children, metric);

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <h2 className="section-title">Fleet</h2>
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
      {table && rows.length > 0 && (
        <FleetTable rows={rows} paramKeys={varyingParams(rows)} metric={metric} runUrl={runUrl} label="Children" />
      )}
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
      <h2 className="section-title">Metadata</h2>
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
        {detail.compacted === false && (
          <><div className="k">metrics</div>
            <div><span className="badge" title="metric streams not compacted yet: charts read slower (vmn-exp compact)">not compacted</span></div></>
        )}
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
