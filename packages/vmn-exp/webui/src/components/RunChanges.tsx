/** The run page's Changes card (plan 20 D7): what this run changed, against
 *  a baseline picked from the server's `/baselines` (its own patch, parent,
 *  fork/rerun origin, previous, best) or any run the page's `?baseline=`
 *  names. Read-only: it renders in every workspace. */
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchRunBaselines } from "../apiRunCode";
import { compareSearch } from "../pages/Compare/selection";
import { appName as toAppName } from "../api";
import Segmented from "./Segmented";
import { baselineChoices, CHANGES_ID, resolveBaseline } from "./runChangesBaseline";
import { PatchChanges, Reason, RunDiffChanges } from "./RunChangesBody";
import "./RunChanges.css";

const NOTHING = "No code changes captured (clean tree) and no earlier run to compare with.";

/** *baseline* is a baseline key or a run ref (null = the D7 default);
 *  *onBaseline* gets the key (or ref) the user picks. */
export default function RunChanges({ ws, app, verstr, baseline, onBaseline }: {
  ws: string; app: string; verstr: string;
  baseline: string | null;
  onBaseline: (keyOrRef: string) => void;
}) {
  const client = useQueryClient();
  const found = useQuery({
    queryKey: ["run-baselines", ws, app, verstr],
    queryFn: () => fetchRunBaselines(ws, app, verstr),
  }, client);
  const b = found.data;
  const choices = b ? baselineChoices(b, baseline) : [];
  const chosenId = b ? resolveBaseline(b, baseline) : null;
  const chosen = choices.find((c) => c.id === chosenId) ?? null;

  let body;
  if (found.error) body = <Reason text={String(found.error)} />;
  else if (!b) body = <Reason text="Loading…" />;
  else if (!chosen) body = <Reason text={NOTHING} />;
  else if (chosen.verstr == null) body = <PatchChanges ws={ws} app={app} verstr={verstr} />;
  else body = <RunDiffChanges ws={ws} app={app} from={chosen.verstr} to={verstr} />;

  return (
    <section className="card run-changes" id={CHANGES_ID} aria-labelledby="run-changes-title">
      <div className="run-changes-head">
        <h2 className="section-title" id="run-changes-title">Changes</h2>
        {chosen && choices.length > 1 && (
          <Segmented
            label="Baseline" options={choices.map((c) => [c.id, c.label] as const)}
            value={chosen.id} onChange={(id) => onBaseline(id.startsWith("ref:") ? id.slice(4) : id)}
          />
        )}
        {chosen && choices.length === 1 && <span className="muted">vs {chosen.label}</span>}
      </div>
      {body}
      {chosen && (
        <div className="run-changes-foot">
          {chosen.verstr == null
            ? <span className="cli-hint">vmn-exp show {toAppName(app)} -v {verstr} --patch</span>
            : (
              <Link to={`/ws/${ws}/app/${app}/compare-runs?${compareSearch("code", [chosen.verstr, verstr])}`}>
                Open in Compare →
              </Link>
            )}
        </div>
      )}
    </section>
  );
}
