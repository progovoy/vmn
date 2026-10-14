/** Compare's guide for an outer run that logs no metrics itself: a note per
 *  such run offering its best run (by the primary goal, else its first run)
 *  in its place, or its runs added (at most OUTER_ADD_CAP). */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { fmtCount, plural } from "../../util";
import { jobSummaryQuery } from "../Job/jobQueries";
import type { OuterInfo, RunChipLabel } from "./useRunLabels";

export const OUTER_ADD_CAP = 20;

const subtree = (ws: string, app: string, v: string, limit: number) =>
  api.experimentsPaged(ws, app, { scope: v, limit, sort: "idx", order: "asc", archived: true })
    .then((page) => page.rows.map((r) => r.verstr));

function OuterRunNote({ ws, app, outer, onBest, onAdd }: {
  ws: string; app: string; outer: OuterInfo;
  onBest: (verstr: string) => void; onAdd: (verstrs: string[]) => void;
}) {
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const { verstr, name, count } = outer;
  const capped = count != null && count > OUTER_ADD_CAP;
  const fail = (e: unknown) => setError(String((e as Error).message ?? e));

  const best = () => client.fetchQuery(jobSummaryQuery(ws, app, verstr))
    .then((s) => s.top[0]?.verstr ?? subtree(ws, app, verstr, 1).then((vs) => vs[0]))
    .then((v) => (v ? onBest(v) : setError("it has no runs yet")), fail);
  const addAll = () => subtree(ws, app, verstr, OUTER_ADD_CAP).then(onAdd, fail);

  return (
    <p className="compare-outer-note" role="note">
      <span>
        <strong>{name}</strong> is an outer run{count != null && ` of ${plural(count, "run")}`} and logs no metrics itself.
      </span>
      <button className="link" onClick={best}>Compare its best run</button>
      <button className="link" onClick={addAll}>
        {capped ? `Add ${OUTER_ADD_CAP} of its ${fmtCount(count)} runs` : count != null ? `Add its ${plural(count, "run")}` : "Add its runs"}
      </button>
      {capped && <span className="muted">capped at {OUTER_ADD_CAP}</span>}
      {error && <span className="muted" role="alert">{error}</span>}
    </p>
  );
}

export default function OuterRunNotes({ ws, app, labels, onReplace, onAdd }: {
  ws: string; app: string; labels: RunChipLabel[];
  onReplace: (ref: string, by: string) => void; onAdd: (verstrs: string[]) => void;
}) {
  const quiet = labels.filter((l) => l.outer && !l.outer.logsMetrics);
  if (!quiet.length) return null;
  return (
    <div className="compare-outer-notes">
      {quiet.map((l) => (
        <OuterRunNote key={l.ref} ws={ws} app={app} outer={l.outer!} onBest={(v) => onReplace(l.ref, v)} onAdd={onAdd} />
      ))}
    </div>
  );
}
