/** The leaderboard's inner cell: an outer run's inner runs in one line
 *  (`5 · 4 running · 1 failed`), each state in its colour and named in
 *  words, with one sentence for screen readers. */
import type { CSSProperties } from "react";
import type { ExperimentRow } from "../types";
import { INNER_COLUMN, innerRunSummary } from "./innerRunColumns";
import "./innerCell.css";

export default function InnerCell({ r, style }: { r: ExperimentRow; style: CSSProperties }) {
  const s = innerRunSummary(r);
  return (
    <td data-col-id={INNER_COLUMN} className="inner-cell" style={style} title={s?.label}>
      {s && (
        <>
          <span aria-hidden="true">
            <span className="inner-total">{s.total}</span>
            {s.parts.map((p) => (
              <span key={p.state}>{" · "}<span className={`inner-${p.state}`}>{p.text}</span></span>
            ))}
          </span>
          <span className="sr-only">{s.label}</span>
        </>
      )}
    </td>
  );
}
