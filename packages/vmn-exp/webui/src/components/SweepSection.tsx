/** The "sweep" section of a sweep's outer run: the spec, its trials and the
 *  best one so far — all from the server's sweep endpoint, so the page and
 *  `vmn-exp sweep status` agree. */
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchSweep, type SweepSpec, type SweepView } from "../apiSweep";
import { rowsPrefix } from "../queries";
import { fmtParam, fmtVal } from "../util";
import StatusPill from "./StatusPill";
import type { RunState } from "../types";

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

export function SweepCard({ view, boardUrl, runUrl }: {
  view: SweepView; boardUrl: string; runUrl: (v: string) => string;
}) {
  const { spec, trials } = view;
  const best = view.summary.best;
  const params = Object.keys(spec.parameters);
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="eyebrow">sweep</div>
      <SpecSummary spec={spec} />
      {best && (
        <div data-testid="sweep-best" style={{ marginTop: 12 }}>
          best trial: <Link className="mono" to={runUrl(best.verstr)}>{best.name || best.verstr}</Link>
          {" "}{spec.metric.name} = <span className="metric best">{fmtVal(best.value)}</span>
        </div>
      )}
      {trials.length === 0 ? (
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
            {trials.map((t) => (
              <tr key={t.verstr} data-testid="sweep-trial"
                className={t.verstr === best?.verstr ? "best" : undefined}>
                <td>{t.trial}</td>
                <td><Link className="mono" to={runUrl(t.verstr)}>{t.name || t.verstr}</Link></td>
                <td>
                  {t.status && <StatusPill status={t.status as RunState} />}
                  {t.stopped_early && <span className="badge">stopped early</span>}
                </td>
                {params.map((p) => (
                  <td key={p} className="mono">{p in t.params ? fmtParam(t.params[p]) : "–"}</td>
                ))}
                <td className="mono">
                  {t.metric_source !== t.verstr && t.value !== null ? (
                    <Link to={runUrl(t.metric_source)} title={`from ${t.metric_source}`}>{fmtVal(t.value)}</Link>
                  ) : fmtVal(t.value)}
                </td>
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

export default function SweepSection({ ws, app, verstr, runUrl }: {
  ws: string; app: string; verstr: string; runUrl: (v: string) => string;
}) {
  const sweep = useQuery({
    // Under the rows prefix, so whatever refreshes the app's lists refreshes this.
    queryKey: [...rowsPrefix(ws, app), "sweep", verstr],
    queryFn: () => fetchSweep(ws, app, verstr),
  });
  if (!sweep.data) return null;
  const boardUrl = `/ws/${ws}/app/${app}?q=${encodeURIComponent(sweepQuery(verstr))}`;
  return <SweepCard view={sweep.data} boardUrl={boardUrl} runUrl={runUrl} />;
}
