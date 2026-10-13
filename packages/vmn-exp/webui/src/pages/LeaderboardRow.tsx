import { memo, useRef, type CSSProperties, type MouseEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { ExperimentRow } from "../types";
import { fmtParam, fmtVal, relTime, rowParams, runHref } from "../util";
import StatusPill from "../components/StatusPill";
import { Icon } from "../components/shell/icons";
import { tagLabel } from "../util/tags";
import {
  DATE_SORT_OF, cellId, columnIds, defaultColumnIds, isGapId, type ColMeta, type ColumnCell, type FleetCol,
} from "./leaderboardColumns";
import InnerCell from "./InnerCell";
import { INNER_COLUMN, isInnerRunId } from "./innerRunColumns";

/** Everything a row needs that is the same for every row — kept as one
 *  memoized object so an unchanged row skips re-rendering entirely. */
const HOVER_INTENT_MS = 120;
export const ROW_HEIGHT = 48;

export interface RowLayout {
  /** One style per entry of *ids*. */
  styles: CSSProperties[];
  /** Column widths (px), per entry of *ids*. */
  widths?: number[];
  total: number;
  /** Column ids in display order (see `defaultColumnIds`); the default
   *  order of the visible columns when omitted. */
  ids?: readonly string[];
  /** Metric and param columns in rendered order, used when *ids* is absent.
   *  Falls back to metricCols + paramCols. */
  cells?: readonly ColumnCell[];
  /** Outer-run management columns (none when omitted). */
  fleetCols?: readonly FleetCol[];
  /** Metric keys in cells order — kept for chart/toolbar consumers. */
  metricCols: string[];
  /** Param keys in cells order — kept for chart/toolbar consumers. */
  paramCols: string[];
  /** Whether the tags column is shown (non-null: shown). */
  tagsIdx?: number | null;
  paramBase?: number;
  noteIdx?: number;
  colMeta: Record<string, ColMeta>;
  /** Highlight column bests only when there is something to beat. */
  showBest: boolean;
  runBase: string;
}

function MetricCell({ id, v, col, style, showBest }: {
  id: string; v: number | string | null | undefined; col: ColMeta; style: CSSProperties; showBest: boolean;
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
    <td data-col-id={id} className={isBar ? "bar-cell" : ""} style={style}>
      {isBar && <span className="bar" style={{ width: `${8 + frac * 62}px` }} />}
      <span className={`metric${isBest ? " best" : ""}`}>{fmtVal(v)}</span>
    </td>
  );
}

const SHORT_DATE = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const shortDate = (iso: string | null | undefined) => (iso ? SHORT_DATE.format(new Date(iso)) : "—");

function FleetCell({ r, c, style }: { r: ExperimentRow; c: string; style: CSSProperties }) {
  const field = DATE_SORT_OF[`c:${c}`];
  const date = field ? r[field] : undefined;
  const text = date !== undefined ? shortDate(date) : "";
  return (
    <td data-col={c} data-col-id={`c:${c}`} className={`num fleet-cell fleet-${c}`} style={style} title={date ?? undefined}>
      {text}
    </td>
  );
}

function CommentsCell({ counts, style }: { counts: ExperimentRow["comments"]; style: CSSProperties }) {
  const text = counts ? `${counts.total}${counts.unresolved ? ` (${counts.unresolved} open)` : ""}` : "";
  return <td data-col-id="c:comments" className="num comments-cell" style={style}>{text}</td>;
}

/** The layout's column ids, in display order. */
export function layoutIds(layout: RowLayout): readonly string[] {
  if (layout.ids) return layout.ids;
  const fleet = layout.fleetCols ?? [];
  const tags = layout.tagsIdx != null;
  return layout.cells
    ? columnIds(fleet, layout.cells.map(cellId), tags)
    : defaultColumnIds(fleet, layout.metricCols, layout.paramCols, tags);
}

/** A row's headline status: an outer's rolled-up tree_status, else its own. */
export const headStatus = (r: ExperimentRow) =>
  (r.kind === "outer" && r.tree_status ? r.tree_status : r.status) as ExperimentRow["status"];

/** The tree level as the `--depth` custom property `innerRows.css` indents by. */
export const depthStyle = (depth: number | undefined) => ({ "--depth": depth ?? 0 }) as CSSProperties;

export function FoldToggle({ r, collapsed, onFold }: {
  r: ExperimentRow; collapsed: boolean; onFold: (r: ExperimentRow) => void;
}) {
  return (
    <button
      className="fold-toggle" aria-expanded={!collapsed}
      aria-label={`${collapsed ? "Expand" : "Collapse"} ${r.verstr}`}
      onClick={() => onFold(r)}
    >
      <Icon name={collapsed ? "chevron-right" : "chevron-down"} size={14} />
    </button>
  );
}

function ExperimentCell({ r, href, style, onPrefetch, collapsed, onFold, innerShown }: {
  r: ExperimentRow; href: string; style: CSSProperties; onPrefetch: (verstr: string) => void;
  /** The inner column counts the inner runs, so this cell doesn't. */
  innerShown: boolean;
  /** Null for a run without inner runs. */
  collapsed: boolean | null;
  onFold: (r: ExperimentRow) => void;
}) {
  return (
    <td style={style} className="exp-cell" data-col-id="experiment">
      <div className="exp-tree" style={depthStyle(r.depth)}>
        <div className="nest">
          {collapsed !== null && <FoldToggle r={r} collapsed={collapsed} onFold={onFold} />}
          {(r.depth ?? 0) > 0 && <span className="nest-mark" title="inner run">⤷</span>}
          <Link
            className={`run-link${r.name ? " run-name" : " mono"}`} to={href} title={r.verstr}
            onFocus={() => onPrefetch(r.verstr)}
          >
            {r.name || r.verstr}
          </Link>
          {r.children && r.children.length > 0 && (() => {
            const tree = r.tree_status && r.tree_status !== r.status ? `tree ${r.tree_status}` : "";
            const text = innerShown ? tree : `${r.children.length} inner${tree ? ` · ${tree}` : ""}`;
            return text && <span className="tree-roll">{text}</span>;
          })()}
        </div>
        <div className="exp-branch">
          {r.name && <span className="mono exp-verstr">{r.verstr}</span>}
          {r.branch}
          {r.status === "failed" && r.error_summary && (
            <span className="exp-error" title={r.error_summary}>{r.error_summary}</span>
          )}
        </div>
      </div>
    </td>
  );
}

export function TagChips({ tags }: { tags: Record<string, string> | undefined }) {
  if (!tags) return null;
  return (
    <>
      {Object.entries(tags).map(([k, v]) => (
        <span key={k} className="tag-chip" title={`tags.${k} = ${v}`}>{tagLabel(k, v)}</span>
      ))}
    </>
  );
}

function Row({
  row: r, index, isSelected, isFlash, isActive, collapsed, layout,
  onToggle, onPrefetch, onFold,
}: {
  row: ExperimentRow;
  index: number;
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
  const { styles, colMeta } = layout;
  const href = runHref(layout.runBase, r.verstr);
  const ids = layoutIds(layout);
  const params = layout.paramCols.length ? rowParams(r) : {};
  // Links and the checkbox handle their own clicks (cmd/middle-click on the
  // link opens a tab); anywhere else on the row opens the run.
  const onClick = (e: MouseEvent) => {
    if ((e.target as HTMLElement).closest("a, input, button")) return;
    navigate(href);
  };

  const cell = (id: string, style: CSSProperties) => {
    const name = id.slice(2);
    switch (id) {
      case "check":
        return (
          <td key={id} data-col-id={id} style={style} className="check-cell">
            <input
              type="checkbox" checked={isSelected} aria-label={`Select ${r.verstr}`}
              onChange={() => {}} onClick={(e) => onToggle(r.verstr, e.shiftKey)}
            />
          </td>
        );
      case "idx":
        return <td key={id} data-col-id={id} className="idx-cell" style={style}>@{r.idx}</td>;
      case "status": {
        const displayStatus = headStatus(r);
        return (
          <td key={id} data-col-id={id} className="status-cell" style={style}>
            {displayStatus && (
              <StatusPill
                status={displayStatus} exitCode={r.exit_code}
                durationSec={r.duration_sec} staleSec={r.stale_sec}
                errorSummary={r.error_summary}
              />
            )}
          </td>
        );
      }
      case "experiment":
        return (
          <ExperimentCell
            key={id} r={r} href={href} style={style} onPrefetch={onPrefetch} collapsed={collapsed} onFold={onFold}
            innerShown={ids.includes(INNER_COLUMN)}
          />
        );
      case "c:tags":
        return <td key={id} data-col-id={id} className="tags-cell" style={style}><TagChips tags={r.tags} /></td>;
      case "c:comments":
        return <CommentsCell key={id} counts={r.comments} style={style} />;
      case "note":
        return <td key={id} data-col-id={id} className="note-cell" style={style}>{r.note}</td>;
      case "when":
        return (
          <td key={id} data-col-id={id} className="when-cell" style={style} title={r.timestamp ?? ""}>
            {relTime(r.timestamp)}
          </td>
        );
    }
    if (isGapId(id)) return <td key={id} aria-hidden style={style} />;
    if (isInnerRunId(id)) return <InnerCell key={id} r={r} style={style} />;
    if (id.startsWith("c:")) return <FleetCell key={id} r={r} c={name} style={style} />;
    if (id.startsWith("m:")) {
      return (
        <MetricCell key={id} id={id} v={r.metrics[name]} col={colMeta[name]} style={style} showBest={layout.showBest} />
      );
    }
    return (
      <td
        key={id} data-col-id={id} className="mono param-cell" style={style}
        title={params[name] != null ? String(params[name]) : undefined}
      >
        {params[name] != null ? fmtParam(params[name]) : "—"}
      </td>
    );
  };

  return (
    <tr
      style={{ height: ROW_HEIGHT }}
      className={`row${(r.depth ?? 0) > 0 ? " inner" : ""}${isSelected ? " checked" : ""}${isFlash ? " flash" : ""}${r.archived ? " archived" : ""}`}
      data-row-index={index}
      data-href={href}
      tabIndex={isActive ? 0 : -1}
      onClick={onClick}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
    >
      {ids.map((id, i) => cell(id, styles[i]))}
    </tr>
  );
}

export default memo(Row);
