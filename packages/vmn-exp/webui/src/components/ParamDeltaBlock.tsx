/** The params an experiments-diff flags (`param: true`, K1/D2) that changed:
 *  a "params changed" count and one row per param, apart from the metrics
 *  (Changes card, Compare code tab). */
import type { ReactNode } from "react";
import type { DiffDelta } from "../types";
import { fmtParam } from "../util";
import "./ParamDeltaBlock.css";

const side = (v: number | null) => (v == null ? "–" : fmtParam(v));

export default function ParamDeltaBlock({ deltas, heads }: {
  deltas: Record<string, DiffDelta>;
  /** The two side columns' `<th>`s; "baseline" / "this run" by default. */
  heads?: [ReactNode, ReactNode];
}) {
  const params = Object.entries(deltas)
    .filter(([, d]) => d.param && d.from !== d.to)
    .sort(([a], [b]) => a.localeCompare(b));
  if (params.length === 0) return null;
  return (
    <section className="param-deltas" aria-label="Params changed">
      <h3 className="param-deltas-title">
        Params changed <span className="param-deltas-count">{params.length}</span>
      </h3>
      <table aria-label="Param changes">
        <thead>
          <tr>
            <th>param</th>
            {heads ?? <><th className="num">baseline</th><th className="num">this run</th></>}
          </tr>
        </thead>
        <tbody>
          {params.map(([k, d]) => (
            <tr key={k}>
              <th scope="row">{k}</th>
              <td className="mono num">{side(d.from)}</td>
              <td className="mono num">{side(d.to)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
