import { memo, type CSSProperties, type MouseEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { ExperimentRow } from "../types";
import { fmtVal, relTime, rowParams } from "../util";
import StatusPill from "../components/StatusPill";
import type { ColMeta } from "./leaderboardColumns";

/** Everything a row needs that is the same for every row — kept as one
 *  memoized object so an unchanged row skips re-rendering entirely. */
export interface RowLayout {
  styles: CSSProperties[];
  total: number;
  metricCols: string[];
  paramCols: string[];
  colMeta: Record<string, ColMeta>;
  /** Highlight column bests only when there is something to beat. */
  showBest: boolean;
  runBase: string;
}

export const runHref = (base: string, verstr: string) => `${base}/run/${encodeURIComponent(verstr)}`;

function MetricCell({ v, col, style, showBest }: {
  v: number | string | null | undefined; col: ColMeta; style: CSSProperties; showBest: boolean;
}) {
  const isBest = showBest && typeof v === "number" && v === col.best;
  const isBar = col.isBar && typeof v === "number";
  let frac = 0;
  if (isBar) {
    const span = col.max - col.min;
    frac = span === 0 ? 1 : ((v as number) - col.min) / span;
    if (col.goal === "min") frac = 1 - frac;
  }
  return (
    <td className={isBar ? "bar-cell" : ""} style={style}>
      {isBar && <span className="bar" style={{ width: `${8 + frac * 62}px` }} />}
      <span className={`metric${isBest ? " best" : ""}`}>{fmtVal(v)}</span>
    </td>
  );
}

function ExperimentCell({ r, href, style, onPrefetch }: {
  r: ExperimentRow; href: string; style: CSSProperties; onPrefetch: (verstr: string) => void;
}) {
  return (
    <td style={style} className="exp-cell">
      <div className="nest" style={{ paddingLeft: (r.depth ?? 0) * 14 }}>
        {(r.depth ?? 0) > 0 && <span className="nest-mark" title="inner run">⤷</span>}
        <Link className="mono run-link" to={href} onFocus={() => onPrefetch(r.verstr)}>
          {r.verstr}
        </Link>
        {r.children && r.children.length > 0 && (
          <span className="tree-roll">
            {r.children.length} inner
            {r.tree_status && r.tree_status !== r.status ? ` · tree ${r.tree_status}` : ""}
          </span>
        )}
      </div>
      <div className="exp-branch">{r.branch}</div>
    </td>
  );
}

function Row({ row: r, start, size, isSelected, isFlash, layout, onToggle, onPrefetch }: {
  row: ExperimentRow;
  start: number;
  size: number;
  isSelected: boolean;
  isFlash: boolean;
  layout: RowLayout;
  onToggle: (verstr: string) => void;
  onPrefetch: (verstr: string) => void;
}) {
  const navigate = useNavigate();
  const { styles, metricCols, paramCols, colMeta } = layout;
  const href = runHref(layout.runBase, r.verstr);
  const paramBase = 4 + metricCols.length;
  const noteIdx = paramBase + paramCols.length;
  const params = paramCols.length ? rowParams(r) : {};
  // Links and the checkbox handle their own clicks (cmd/middle-click on the
  // link opens a tab); anywhere else on the row opens the run.
  const onClick = (e: MouseEvent) => {
    if ((e.target as HTMLElement).closest("a, input")) return;
    navigate(href);
  };

  return (
    <tr
      style={{
        position: "absolute", top: 0, left: 0, width: layout.total, height: size,
        transform: `translateY(${start}px)`, display: "table", tableLayout: "fixed",
      }}
      className={`row${isSelected ? " checked" : ""}${isFlash ? " flash" : ""}`}
      onClick={onClick}
      onMouseEnter={() => onPrefetch(r.verstr)}
    >
      <td style={styles[0]} className="check-cell">
        <input type="checkbox" checked={isSelected} onChange={() => onToggle(r.verstr)} />
      </td>
      <td className="idx-cell" style={styles[1]}>@{r.idx}</td>
      <td className="status-cell" style={styles[2]}>
        {r.status && (
          <StatusPill
            status={r.status} exitCode={r.exit_code}
            durationSec={r.duration_sec} staleSec={r.stale_sec}
          />
        )}
      </td>
      <ExperimentCell r={r} href={href} style={styles[3]} onPrefetch={onPrefetch} />
      {metricCols.map((m, i) => (
        <MetricCell key={m} v={r.metrics[m]} col={colMeta[m]} style={styles[4 + i]} showBest={layout.showBest} />
      ))}
      {paramCols.map((p, i) => (
        <td key={`p-${p}`} className="mono param-cell" style={styles[paramBase + i]}>
          {params[p] != null ? String(params[p]) : "—"}
        </td>
      ))}
      <td className="note-cell" style={styles[noteIdx]}>{r.note}</td>
      <td className="when-cell" style={styles[noteIdx + 1]} title={r.timestamp ?? ""}>
        {relTime(r.timestamp)}
      </td>
    </tr>
  );
}

export default memo(Row);
