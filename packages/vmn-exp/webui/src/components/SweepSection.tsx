/** The "sweep" section of a sweep's outer run: the spec, its trials and the
 *  best one so far — all from the server's sweep endpoint, so the page and
 *  `vmn-exp sweep status` agree. */
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchSweep, type SweepSpec, type SweepTrial, type SweepView } from "../apiSweep";
import { rowsPrefix } from "../queries";
import { fmtVal } from "../util";
import type { RunState } from "../types";
import FleetTable from "./FleetTable";
import SweepTrialsChart from "./SweepTrialsChart";
import { fleetLabel, varyingParams, type FleetRow } from "./fleetRows";

export type { SweepSpec };

/** The sweep spec a run's metadata carries, or null for a plain run. */
export function sweepSpecOf(metadata: Record<string, unknown>): SweepSpec | null {
  const spec = metadata.sweep;
  return spec && typeof spec === "object" && "metric" in spec ? (spec as SweepSpec) : null;
}

/** The leaderboard filter that selects a sweep's trials. */
export const sweepQuery = (verstr: string) => `parent = "${verstr}"`;

function describeParam(p: Record<string, unknown>): string {
  if ("value" in p) return String(p.value);
  if (Array.isArray(p.values)) return p.values.map(String).join(", ");
  if (p.distribution === "normal") return `normal μ=${p.mu} σ=${p.sigma}`;
  return `${p.distribution} ${p.min} – ${p.max}`;
}

function SpecSummary({ spec }: { spec: SweepSpec }) {
  return (
    <div className="kv" data-testid="sweep-spec">
      <div className="k">method</div>
      <div className="mono">{spec.method}</div>
      <div className="k">metric</div>
      <div className="mono">{spec.metric.name} ({spec.metric.goal})</div>
      {spec.run_cap != null && (<><div className="k">limit</div><div>run cap {spec.run_cap}</div></>)}
      {spec.early_terminate && (
        <><div className="k">early stop</div>
          <div>{spec.early_terminate.type} after {spec.early_terminate.min_iter ?? 1} steps</div></>
      )}
      {Object.entries(spec.parameters).map(([name, p]) => (
        <div key={name} style={{ display: "contents" }}>
          <div className="k">{name}</div>
          <div className="mono">{describeParam(p)}</div>
        </div>
      ))}
    </div>
  );
}

/** The fleet table's rows for a sweep's trials, labelled `@N name` once
 *  *idxOf* knows a trial's index. */
function trialRows(trials: SweepTrial[], idxOf: (v: string) => number | null): FleetRow[] {
  return trials.map((t) => ({
    verstr: t.verstr, label: fleetLabel({ verstr: t.verstr, idx: idxOf(t.verstr), name: t.name }),
    status: (t.status as RunState | null) ?? null, params: t.params, value: t.value,
    valueFrom: t.metric_source !== t.verstr ? t.metric_source : undefined,
    progress: null, trial: t.trial, stoppedEarly: t.stopped_early,
  }));
}

export function SweepCard({ view, boardUrl, runUrl, idxOf = () => null }: {
  view: SweepView; boardUrl: string; runUrl: (v: string) => string;
  /** A trial's `@N`, from the outer run's fleet. */
  idxOf?: (verstr: string) => number | null;
}) {
  const { spec, trials } = view;
  const best = view.summary.best;
  const rows = trialRows(trials, idxOf);
  const paramKeys = varyingParams(rows, Object.keys(spec.parameters));
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <h2 className="section-title">Sweep</h2>
      <SpecSummary spec={spec} />
      {best && (
        <div data-testid="sweep-best" style={{ marginTop: 12 }}>
          best trial: <Link to={runUrl(best.verstr)} title={best.verstr}>
            {fleetLabel({ verstr: best.verstr, idx: idxOf(best.verstr), name: best.name })}
          </Link>
          {" "}{spec.metric.name} = <span className="metric best">{fmtVal(best.value)}</span>
        </div>
      )}
      {trials.length === 0 ? (
        <div className="empty" style={{ padding: 12 }}>No trials yet — start one with vmn-exp sweep agent.</div>
      ) : (
        <>
          <FleetTable rows={rows} paramKeys={paramKeys} metric={spec.metric} runUrl={runUrl}
            best={best?.verstr ?? null} rowTestId="sweep-trial" label="Trials" />
          <SweepTrialsChart rows={rows} paramKeys={paramKeys} metric={spec.metric} />
        </>
      )}
      <Link className="link" to={boardUrl} style={{ display: "inline-block", marginTop: 8 }}>
        Open the trials on the leaderboard
      </Link>
    </div>
  );
}

export default function SweepSection({ ws, app, verstr, runUrl, idxOf }: {
  ws: string; app: string; verstr: string; runUrl: (v: string) => string;
  idxOf?: (verstr: string) => number | null;
}) {
  const sweep = useQuery({
    // Under the rows prefix, so whatever refreshes the app's lists refreshes this.
    queryKey: [...rowsPrefix(ws, app), "sweep", verstr],
    queryFn: () => fetchSweep(ws, app, verstr),
  });
  if (!sweep.data) return null;
  const boardUrl = `/ws/${ws}/app/${app}?q=${encodeURIComponent(sweepQuery(verstr))}`;
  return <SweepCard view={sweep.data} boardUrl={boardUrl} runUrl={runUrl} idxOf={idxOf} />;
}
