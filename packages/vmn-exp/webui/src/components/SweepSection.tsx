/** The "sweep" section of a sweep's outer run: the spec, its trials (the
 *  run's inner jobs) and the best one so far. */
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { rowsPrefix } from "../queries";
import type { ExperimentRow } from "../types";
import { fmtParam, fmtVal, paramValue } from "../util";
import { finiteOrNull } from "../util/stats";
import StatusPill from "./StatusPill";

export interface SweepSpec {
  method: string;
  metric: { name: string; goal: "min" | "max" };
  parameters: Record<string, Record<string, unknown>>;
  run_cap?: number;
  early_terminate?: { type: string; min_iter?: number };
}

/** The sweep spec a run's metadata carries, or null for a plain run. */
export function sweepSpecOf(metadata: Record<string, unknown>): SweepSpec | null {
  const spec = metadata.sweep;
  return spec && typeof spec === "object" && "metric" in spec ? (spec as SweepSpec) : null;
}

/** The leaderboard filter that selects a sweep's trials. */
export const sweepQuery = (verstr: string) => `parent = "${verstr}"`;

const trialNo = (r: ExperimentRow) => Number(r.tags?.sweep_trial ?? -1);
const attemptNo = (r: ExperimentRow) => Number(r.tags?.sweep_attempt ?? 0);

const metricOf = (spec: SweepSpec, r: ExperimentRow) => finiteOrNull(r.metrics?.[spec.metric.name]);

export function bestTrial(spec: SweepSpec, rows: ExperimentRow[]): ExperimentRow | null {
  let best: ExperimentRow | null = null;
  let bestVal: number | null = null;
  for (const r of rows) {
    const v = metricOf(spec, r);
    if (v !== null && (bestVal === null || (spec.metric.goal === "min" ? v < bestVal : v > bestVal))) {
      best = r;
      bestVal = v;
    }
  }
  return best;
}

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

export function SweepCard({ spec, trials, boardUrl, runUrl }: {
  spec: SweepSpec; verstr: string; trials: ExperimentRow[];
  boardUrl: string; runUrl: (v: string) => string;
}) {
  const ordered = [...trials].sort((a, b) => trialNo(a) - trialNo(b) || attemptNo(a) - attemptNo(b));
  const best = bestTrial(spec, ordered);
  const params = Object.keys(spec.parameters);
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="eyebrow">sweep</div>
      <SpecSummary spec={spec} />
      {best && (
        <div data-testid="sweep-best" style={{ marginTop: 12 }}>
          best trial: <Link className="mono" to={runUrl(best.verstr)}>{best.name || best.verstr}</Link>
          {" "}{spec.metric.name} = <span className="metric best">{fmtVal(metricOf(spec, best))}</span>
        </div>
      )}
      {ordered.length === 0 ? (
        <div className="empty" style={{ padding: 12 }}>No trials yet — start one with vmn-exp sweep agent.</div>
      ) : (
        <table style={{ marginTop: 12 }}>
          <thead>
            <tr>
              <th>trial</th><th>run</th><th>status</th>
              {params.map((p) => <th key={p}>{p}</th>)}
              <th>{spec.metric.name}</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((r) => (
              <tr key={r.verstr} data-testid="sweep-trial" className={r === best ? "best" : undefined}>
                <td>{trialNo(r)}</td>
                <td><Link className="mono" to={runUrl(r.verstr)}>{r.name || r.verstr}</Link></td>
                <td>
                  {r.status && <StatusPill status={r.status} />}
                  {r.tags?.stopped_early === "true" && <span className="badge">stopped early</span>}
                </td>
                {params.map((p) => {
                  const v = paramValue(r, p);
                  return <td key={p} className="mono">{v === undefined ? "–" : fmtParam(v)}</td>;
                })}
                <td className="mono">{fmtVal(metricOf(spec, r))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Link className="link" to={boardUrl} style={{ display: "inline-block", marginTop: 8 }}>
        Compare trials on the leaderboard (parallel coordinates)
      </Link>
    </div>
  );
}

/** Most trials a sweep section lists (the list endpoint's page cap). */
const MAX_TRIALS = 1000;

export default function SweepSection({ ws, app, verstr, spec, runUrl }: {
  ws: string; app: string; verstr: string; spec: SweepSpec; runUrl: (v: string) => string;
}) {
  const query = sweepQuery(verstr);
  const trials = useQuery({
    // Under the rows prefix, so whatever refreshes the app's lists refreshes this.
    queryKey: [...rowsPrefix(ws, app), "sweep", verstr],
    queryFn: () => api.experimentsPaged(ws, app, { query, limit: MAX_TRIALS }),
  });
  const boardUrl = `/ws/${ws}/app/${app}?q=${encodeURIComponent(query)}`;
  return (
    <SweepCard spec={spec} verstr={verstr} trials={trials.data?.rows ?? []}
      boardUrl={boardUrl} runUrl={runUrl} />
  );
}
