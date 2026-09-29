import { Link } from "react-router-dom";

/** The query listing the reruns of *verstr*. */
export const rerunsQuery = (verstr: string) => `rerun_of = "${verstr}"`;

/** The reproduce card's rerun hint and a leaderboard of the run's reruns —
 *  only for a run that recorded a command to rerun. */
export function RerunHints({ boardBase, appName, verstr, command }: {
  boardBase: string; appName: string; verstr: string; command?: string[] | null;
}) {
  if (!command || command.length === 0) return null;
  return (
    <>
      <div className="cli-hint">vmn-exp rerun {appName} -v {verstr}</div>
      <Link className="link" to={`${boardBase}?q=${encodeURIComponent(rerunsQuery(verstr))}`}>
        reruns →
      </Link>
    </>
  );
}
