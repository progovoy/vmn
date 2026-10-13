/** The job's Failures tab (plan 23 W5): its failed and stuck runs
 *  clustered by failure signature, the biggest first. */
import { plural } from "../../util";
import FailureClusterCard from "./FailureClusterCard";
import { useJobFailures } from "./jobQueries";

export default function JobFailures({ ws, app, verstr, failed = 0 }: {
  ws: string; app: string; verstr: string;
  /** The rollup's failed + stuck count: the clusters refetch when it moves. */
  failed?: number;
}) {
  const q = useJobFailures(ws, app, verstr, failed);
  if (q.error && !q.data) {
    return (
      <div className="card error" role="alert">
        Could not load the failures: {q.error.message}{" "}
        <button type="button" className="link" onClick={() => void q.refetch()}>Retry</button>
      </div>
    );
  }
  if (!q.data) {
    return <div className="card skeleton" aria-label="loading"><div className="line" /><div className="line" /></div>;
  }
  const { total_failed: total, clusters } = q.data;
  if (!clusters.length) return <div className="card job-good">No failures. Every finished run succeeded.</div>;
  return (
    <>
      <p className="job-failures-sum">
        {`${plural(total, "failed run")} in ${plural(clusters.length, "cluster")}`}
      </p>
      <ul className="job-clusters">
        {clusters.map((c) => <FailureClusterCard key={c.sig} ws={ws} app={app} jobVerstr={verstr} cluster={c} />)}
      </ul>
    </>
  );
}
