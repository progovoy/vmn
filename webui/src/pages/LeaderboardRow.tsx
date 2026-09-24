import { memo, useRef, type CSSProperties, type MouseEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { ExperimentRow } from "../types";
import { fmtVal, relTime, rowParams, runHref } from "../util";
import StatusPill from "../components/StatusPill";
import type { ColMeta } from "./leaderboardColumns";

/** Everything a row needs that is the same for every row — kept as one
 *  memoized object so an unchanged row skips re-rendering entirely. */
const HOVER_INTENT_MS = 120;

export interface RowLayout {
  styles: CSSProperties[];
  total: number;
  metricCols: string[];
  paramCols: string[];
  /** Index of the first param column, the tags column (null: none) and the note column. */
  paramBase: number;
  tagsIdx: number | null;
  noteIdx: number;
  colMeta: Record<string, ColMeta>;
  /** Highlight column bests only when there is something to beat. */
  showBest: boolean;
  runBase: string;
}

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

function FoldToggle({ r, collapsed, onFold }: {
  r: ExperimentRow; collapsed: boolean; onFold: (r: ExperimentRow) => void;
}) {
  return (
    <button
      className="fold-toggle" aria-expanded={!collapsed}
      aria-label={`${collapsed ? "Expand" : "Collapse"} ${r.verstr}`}
      onClick={() => onFold(r)}
    >
      {collapsed ? "▸" : "▾"}
    </button>
  );
}

function ExperimentCell({ r, href, style, onPrefetch, collapsed, onFold }: {
  r: ExperimentRow; href: string; style: CSSProperties; onPrefetch: (verstr: string) => void;
  /** Null for a run without inner runs. */
  collapsed: boolean | null;
  onFold: (r: ExperimentRow) => void;
}) {
  return (
    <td style={style} className="exp-cell">
      <div className="nest" style={{ paddingLeft: (r.depth ?? 0) * 14 }}>
        {collapsed !== null && <FoldToggle r={r} collapsed={collapsed} onFold={onFold} />}
        {(r.depth ?? 0) > 0 && <span className="nest-mark" title="inner run">⤷</span>}
        <Link className={`run-link${r.name ? " run-name" : " mono"}`} to={href} onFocus={() => onPrefetch(r.verstr)}>
          {r.name || r.verstr}
        </Link>
        {r.children && r.children.length > 0 && (
          <span className="tree-roll">
            {r.children.length} inner
            {r.tree_status && r.tree_status !== r.status ? ` · tree ${r.tree_status}` : ""}
          </span>
        )}
      </div>
      <div className="exp-branch">
        {r.name && <span className="mono exp-verstr">{r.verstr}</span>}
        {r.branch}
      </div>
    </td>
  );
}

export function TagChips({ tags }: { tags: Record<string, string> | undefined }) {
  if (!tags) return null;
  return (
    <>
      {Object.entries(tags).map(([k, v]) => (
        <span key={k} className="tag-chip" title={`tags.${k} = ${v}`}>{v ? `${k}: ${v}` : k}</span>
      ))}
    </>
  );
}

function Row({
  row: r, index, start, size, isSelected, isFlash, isActive, collapsed, layout,
  onToggle, onPrefetch, onFold,
}: {
  row: ExperimentRow;
  index: number;
  start: number;
  size: number;
  isSelected: boolean;
  isFlash: boolean;
  /** The table's one tab stop (roving tabindex). */
  isActive: boolean;
  collapsed: boolean | null;
  layout: RowLayout;
  /** *range*: extend the selection from the last toggled row (shift-click). */
  onToggle: (verstr: string, range: boolean) => void;
  onPrefetch: (verstr: string) => void;
  onFold: (r: ExperimentRow) => void;
}) {
  const navigate = useNavigate();
  // Prefetch on a resting pointer, not on every row a scroll slides under it.
  const hover = useRef<ReturnType<typeof setTimeout>>();
  const onEnter = () => { hover.current = setTimeout(() => onPrefetch(r.verstr), HOVER_INTENT_MS); };
  const onLeave = () => clearTimeout(hover.current);
  const { styles, metricCols, paramCols, colMeta, paramBase, tagsIdx, noteIdx } = layout;
  const href = runHref(layout.runBase, r.verstr);
  const params = paramCols.length ? rowParams(r) : {};
  // Links and the checkbox handle their own clicks (cmd/middle-click on the
  // link opens a tab); anywhere else on the row opens the run.
  const onClick = (e: MouseEvent) => {
    if ((e.target as HTMLElement).closest("a, input, button")) return;
    navigate(href);
  };

  return (
    <tr
      style={{
        position: "absolute", top: 0, left: 0, width: layout.total, height: size,
        transform: `translateY(${start}px)`, display: "table", tableLayout: "fixed",
      }}
      className={`row${isSelected ? " checked" : ""}${isFlash ? " flash" : ""}${r.archived ? " archived" : ""}`}
      data-row-index={index}
      data-href={href}
      tabIndex={isActive ? 0 : -1}
      onClick={onClick}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
    >
      <td style={styles[0]} className="check-cell">
        <input
          type="checkbox" checked={isSelected} aria-label={`Select ${r.verstr}`}
          onChange={() => {}} onClick={(e) => onToggle(r.verstr, e.shiftKey)}
        />
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
      <ExperimentCell
        r={r} href={href} style={styles[3]} onPrefetch={onPrefetch} collapsed={collapsed} onFold={onFold}
      />
      {metricCols.map((m, i) => (
        <MetricCell key={m} v={r.metrics[m]} col={colMeta[m]} style={styles[4 + i]} showBest={layout.showBest} />
      ))}
      {paramCols.map((p, i) => (
        <td key={`p-${p}`} className="mono param-cell" style={styles[paramBase + i]}>
          {params[p] != null ? String(params[p]) : "—"}
        </td>
      ))}
      {tagsIdx !== null && (
        <td className="tags-cell" style={styles[tagsIdx]}><TagChips tags={r.tags} /></td>
      )}
      <td className="note-cell" style={styles[noteIdx]}>{r.note}</td>
      <td className="when-cell" style={styles[noteIdx + 1]} title={r.timestamp ?? ""}>
        {relTime(r.timestamp)}
      </td>
    </tr>
  );
}

export default memo(Row);
