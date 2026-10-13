/** One failure cluster (plan 23 W5): what it is, how big, when, where, the
 *  params overrepresented in it, and one example run — its output tail
 *  loaded only when expanded; plus the copy-first actions. */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { appName as toAppName } from "../../api";
import type { FailureCluster } from "../../apiJob";
import { CopyButton } from "../../components/ui";
import { runQuery } from "../../queries";
import { storeUriOf } from "../../shell/cliCommands";
import { usePageScope } from "../../shell/usePageScope";
import { plural, relTime, runHref } from "../../util";
import { failureQuery, paramShareText, rerunCommand, sharePct } from "./jobData";
import { jobTabHref } from "./jobQueries";

function OutputTail({ ws, app, verstr }: { ws: string; app: string; verstr: string }) {
  const q = useQuery(runQuery(ws, app, verstr), useQueryClient());
  if (q.error) return <p className="error" role="alert">{String(q.error)}</p>;
  if (!q.data) return <div className="skeleton" aria-label="loading"><div className="line" /></div>;
  const tail = q.data.output_tail;
  if (!tail?.lines.length) return <p className="muted">This run kept no output.</p>;
  return (
    <pre className="job-tail mono">{tail.truncated ? "…\n" : ""}{tail.lines.join("\n")}</pre>
  );
}

function Example({ ws, app, verstr }: { ws: string; app: string; verstr: string }) {
  const [open, setOpen] = useState(false);
  const scope = usePageScope(ws);
  const command = rerunCommand(toAppName(app), verstr, storeUriOf(scope.workspace));
  return (
    <div className="job-example">
      <span className="muted">example </span>
      <Link className="mono" to={runHref(`/ws/${ws}/app/${app}`, verstr)}>{verstr}</Link>
      <button type="button" className="link" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? "Hide output tail" : "Show output tail"}
      </button>
      <CopyButton text={command} className="link" label={`Copy rerun command: ${command}`} />
      {open && <OutputTail ws={ws} app={app} verstr={verstr} />}
    </div>
  );
}

export default function FailureClusterCard({ ws, app, jobVerstr, cluster }: {
  ws: string; app: string; jobVerstr: string; cluster: FailureCluster;
}) {
  const runBase = runHref(`/ws/${ws}/app/${app}`, jobVerstr);
  const pct = sharePct(cluster.share);
  const runsQuery = failureQuery(cluster.sig);
  return (
    <li className="card job-cluster" aria-label={`${cluster.label}: ${plural(cluster.count, "run")}`}>
      <div className="job-cluster-head">
        <span className="job-cluster-label" title={cluster.sig}>{cluster.label}</span>
        <span className="job-cluster-count">{plural(cluster.count, "run")}</span>
        <span className="job-share" role="meter" aria-label="share of failures"
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
          <span className="job-share-bar" style={{ width: `${pct}%` }} />
        </span>
        <span className="muted mono">{pct}%</span>
      </div>
      <div className="job-cluster-meta muted">
        {cluster.first_at && <span>first seen {relTime(cluster.first_at)}</span>}
        {cluster.last_at && <span>last seen {relTime(cluster.last_at)}</span>}
        {cluster.hosts.length > 0 && (
          <span>hosts {cluster.hosts.map((h) => <span key={h.host} className="mono job-chip">{`${h.host} (${h.count})`}</span>)}</span>
        )}
      </div>
      {cluster.params.length > 0 && (
        <ul className="job-cluster-params" aria-label="Overrepresented params">
          {cluster.params.map((p) => <li key={p.key} className="mono">{paramShareText(p)}</li>)}
        </ul>
      )}
      {runsQuery && (
        <div className="job-cluster-actions">
          <Link to={jobTabHref(runBase, "runs", { q: runsQuery })}>Show these runs</Link>
        </div>
      )}
      {cluster.example_verstr && <Example ws={ws} app={app} verstr={cluster.example_verstr} />}
    </li>
  );
}
