import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Fleet, RunState, RunStatus } from "../types";
import { fmtDuration } from "../util";
import StatusPill from "../components/StatusPill";
import OuterBadge from "../components/OuterBadge";
import { isOuterRun, outerRunCount } from "../util/outerRun";
import { sweepIncompleteLabel } from "../util/sweepProgress";
import { ImportedBadge } from "./RunProvenance";
import type { RunSummary } from "./runSummary";
import "./runHead.css";

/** "16/16 inner": an outer run's finished children of the ones expected
 *  (lost ones, stuck when it ended, finished failed). */
export function innerCount(fleet: Fleet): string {
  const done = (fleet.counts.succeeded ?? 0) + (fleet.counts.failed ?? 0) + (fleet.lost ?? 0);
  return `${done}/${fleet.expected} inner`;
}

/** The status pill under the page title: an outer run's tree status (D12),
 *  its own status only when that tells something more. */
function StatusParts({ st, runUrl }: { st: RunStatus; runUrl: (v: string) => string }) {
  const isOuter = st.kind === "outer" && st.tree_status;
  const primary = isOuter ? st.tree_status as RunState : st.status;
  const showOwn = isOuter && (
    st.status === "failed" || st.status === "stuck"
    || (st.status === "running" && st.status !== st.tree_status)
  );
  const roll = isOuter && (sweepIncompleteLabel(st) ?? (st.fleet && innerCount(st.fleet)));
  return (
    <>
      <StatusPill status={primary} exitCode={st.exit_code} durationSec={st.duration_sec} staleSec={st.stale_sec}
        releasedAt={isOuter ? null : st.released_at} />
      {roll && <span className="tree-roll">{roll}</span>}
      {showOwn && <span className="tree-roll">own {st.status}</span>}
      {st.status === "stuck" && st.stale_sec != null && (
        <span className="stale">⚠ no heartbeat for {fmtDuration(st.stale_sec)}</span>
      )}
      {!isOuter && st.tree_status && st.tree_status !== st.status && (
        <span className="tree-roll">tree {st.tree_status}</span>
      )}
      {st.parent && (
        <span className="run-parent">inner run of <Link className="mono" to={runUrl(st.parent)}>{st.parent}</Link></span>
      )}
    </>
  );
}

/** What the run is (D5 1): name, verstr and branch, the header actions
 *  (*actions*), then a line with @N, the status and the base version. */
export default function RunHead({ ws, app, summary, importedFrom, runUrl, actions }: {
  ws: string; app: string; summary: RunSummary; importedFrom?: string | null;
  runUrl: (v: string) => string; actions: ReactNode;
}) {
  return (
    <>
      <Link className="back-link" to={`/ws/${ws}/app/${app}`}>← experiments</Link>
      <div className="page-head run-head" style={{ alignItems: "center", marginBottom: 6 }}>
        <h1 className={summary.name ? undefined : "mono"} style={{ fontSize: 20 }}>
          {summary.name || summary.verstr}
        </h1>
        {summary.name && <span className="mono run-verstr">{summary.verstr}</span>}
        {summary.branch && <span className="badge">{summary.branch}</span>}
        {actions}
      </div>
      <div className="status-head run-status-line">
        {summary.idx != null && <span className="mono run-idx">@{summary.idx}</span>}
        {summary.status && <StatusParts st={summary.status} runUrl={runUrl} />}
        {summary.status && isOuterRun(summary.status) && (
          <OuterBadge count={outerRunCount(summary.status)} to={runUrl(summary.verstr)} />
        )}
        {summary.baseVersion && <span className="run-base">base {summary.baseVersion}</span>}
        <ImportedBadge importedFrom={importedFrom} />
      </div>
    </>
  );
}
