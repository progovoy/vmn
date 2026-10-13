/** The Changes card's pieces: the metric delta (top goal metrics by |Δ|),
 *  the files list and the expandable diff (params: ParamDeltaBlock). */
import { useState } from "react";
import type { PatchFile } from "../apiRunCode";
import type { DiffDelta } from "../types";
import { fmtVal } from "../util";
import DiffText from "./DiffText";
import { deltaTone, fmtDelta, numericChange } from "./diffDeltaTone";

/** Metrics shown before "+N more". */
export const TOP_METRICS = 5;

type Delta = [string, DiffDelta];

const change = ([, d]: Delta) => numericChange(d);

/** Goal metrics first, each group by |Δ| descending, non-numeric last. */
function ranked(deltas: Delta[]): Delta[] {
  const size = (e: Delta) => Math.abs(change(e) ?? -1);
  return [...deltas].sort((a, b) =>
    Number(b[1].goal != null) - Number(a[1].goal != null) || size(b) - size(a));
}

export function MetricDelta({ deltas }: { deltas: Record<string, DiffDelta> }) {
  const [all, setAll] = useState(false);
  const metrics = ranked(Object.entries(deltas).filter(([, d]) => !d.param));
  if (metrics.length === 0) return null;
  const shown = all ? metrics : metrics.slice(0, TOP_METRICS);
  const more = metrics.length - shown.length;
  return (
    <div className="changes-metrics">
      <table aria-label="Metric changes">
        <thead>
          <tr><th>metric</th><th className="num">baseline</th><th className="num">this run</th><th className="num">Δ</th></tr>
        </thead>
        <tbody>
          {shown.map((entry) => {
            const [k, d] = entry;
            const diff = change(entry);
            return (
              <tr key={k}>
                <th scope="row">{k}</th>
                <td className="metric num">{fmtVal(d.from)}</td>
                <td className="metric num">{fmtVal(d.to)}</td>
                <td className={`metric num delta ${deltaTone(d, diff)}`}>
                  {fmtDelta(diff)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {more > 0 && <button type="button" className="link" onClick={() => setAll(true)}>+{more} more</button>}
    </div>
  );
}

export function FilesList({ files }: { files: PatchFile[] }) {
  if (files.length === 0) return null;
  return (
    <ul className="changes-files" aria-label="Changed files">
      {files.map((f) => (
        <li key={f.path}>
          <span className="mono path">{f.path}</span>
          <span className="add">+{f.added}</span>
          <span className="del">−{f.removed}</span>
        </li>
      ))}
    </ul>
  );
}

export function DiffToggle({ text, truncated }: { text: string; truncated?: boolean }) {
  const [open, setOpen] = useState(false);
  if (!text.trim()) return null;
  return (
    <div className="changes-diff">
      <button type="button" className="link" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "Hide diff" : "Show diff"}
      </button>
      {truncated && <span className="muted"> truncated</span>}
      {open && <DiffText text={text} />}
    </div>
  );
}
