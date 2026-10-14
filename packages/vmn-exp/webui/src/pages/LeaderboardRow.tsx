import { memo, useRef, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import type { ExperimentRow } from "../types";
import type { Density } from "../util/density";
import type { MemberPlace } from "../util/groupItems";
import { fmtParam, fmtVal, relTime, rowParams, runHref } from "../util";
import RowCheckbox from "../components/RowCheckbox";
import StatusPill from "../components/StatusPill";
import { useRowNavigate } from "../hooks/useRowNavigate";
import { tagLabel } from "../util/tags";
import { sweepIncompleteLabel } from "../util/sweepProgress";
import {
  DATE_SORT_OF, cellId, columnIds, defaultColumnIds, isGapId, type ColMeta, type ColumnCell, type FleetCol,
} from "./leaderboardColumns";

/** Everything a row needs that is the same for every row — kept as one
 *  memoized object so an unchanged row skips re-rendering entirely. */
export const HOVER_INTENT_MS = 120;
export const ROW_HEIGHT = 48;
/** A compact board's one-line rows (plan 23 W8). */
export const COMPACT_ROW_HEIGHT = 32;

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
  /** A flat board's query for its run links at *index* (a job's Runs tab
   *  carries its order to the run page, plan 23 W7). */
  runSearch?: (index: number) => string;
  /** Comfortable when omitted. */
  density?: Density;
}

/** The height of every row of a board laid out by *layout*. */
export const rowHeight = (layout: RowLayout) => densityRowHeight(layout.density);

/** A board row's height at *density* (comfortable when omitted). */
export const densityRowHeight = (density: Density | undefined) =>
  density === "compact" ? COMPACT_ROW_HEIGHT : ROW_HEIGHT;

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

/** A run's own start or end (`c:started`/`c:ended`). */
function DateCell({ r, c, style }: { r: ExperimentRow; c: string; style: CSSProperties }) {
  const field = DATE_SORT_OF[`c:${c}`];
  const date = field ? r[field] : undefined;
  const text = date != null ? shortDate(date) : "";
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

/** An outer run's rollup beside its name: its tree status where it differs
 *  from its own, and an incomplete sweep's `16/20 · incomplete`. */
function treeRoll(r: ExperimentRow): string {
  if (!r.children?.length) return "";
  const tree = r.tree_status && r.tree_status !== r.status ? `tree ${r.tree_status}` : "";
  return [tree, sweepIncompleteLabel(r)].filter(Boolean).join(" · ");
}

/** A compact row's name tooltip: the sub-line it has no room for. */
const subLineTitle = (r: ExperimentRow) =>
  [r.verstr, r.branch, r.status === "failed" ? r.error_summary : null].filter(Boolean).join(" · ");

function ExperimentCell({ r, href, style, onPrefetch, member, compact }: {
  r: ExperimentRow; href: string; style: CSSProperties; onPrefetch: (verstr: string) => void; member: boolean;
  compact: boolean;
}) {
  const roll = treeRoll(r);
  const body = (
    <>
      <div className="nest">
        <Link
          className={`run-link${r.name ? " run-name" : " mono"}`} to={href}
          title={compact ? subLineTitle(r) : r.verstr}
          onFocus={() => onPrefetch(r.verstr)}
        >
          {r.name || r.verstr}
        </Link>
        {roll && <span className="tree-roll">{roll}</span>}
      </div>
      {!compact && <div className="exp-branch">
        {r.name && <span className="mono exp-verstr">{r.verstr}</span>}
        {r.branch}
        {r.status === "failed" && r.error_summary && (
          <span className="exp-error" title={r.error_summary}>{r.error_summary}</span>
        )}
      </div>}
    </>
  );
  return (
    <td style={style} className="exp-cell" data-col-id="experiment">
      {member ? <div className="group-member-body">{body}</div> : body}
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
  row: r, index, isSelected, isFlash, isActive, layout, onToggle, onPrefetch, member,
}: {
  row: ExperimentRow;
  index: number;
  isSelected: boolean;
  isFlash: boolean;
  /** The table's one tab stop (roving tabindex). */
  isActive: boolean;
  layout: RowLayout;
  /** *range*: extend the selection from the last toggled row (shift-click). */
  onToggle: (verstr: string, range: boolean) => void;
  onPrefetch: (verstr: string) => void;
  /** Its place under a group header, when it is a group's member. */
  member?: MemberPlace;
}) {
  // Prefetch on a resting pointer, not on every row a scroll slides under it.
  const hover = useRef<ReturnType<typeof setTimeout>>();
  const onEnter = () => { hover.current = setTimeout(() => onPrefetch(r.verstr), HOVER_INTENT_MS); };
  const onLeave = () => clearTimeout(hover.current);
  const { styles, colMeta } = layout;
  const href = runHref(layout.runBase, r.verstr) + (member ? "" : layout.runSearch?.(index) ?? "");
  const ids = layoutIds(layout);
  const params = layout.paramCols.length ? rowParams(r) : {};
  const onClick = useRowNavigate(href);

  const cell = (id: string, style: CSSProperties) => {
    const name = id.slice(2);
    switch (id) {
      case "check":
        return (
          <td key={id} data-col-id={id} style={style} className="check-cell">
            <RowCheckbox verstr={r.verstr} checked={isSelected} onToggle={onToggle} />
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
            key={id} r={r} href={href} style={style} onPrefetch={onPrefetch} member={!!member}
            compact={layout.density === "compact"}
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
    if (id.startsWith("c:")) return <DateCell key={id} r={r} c={name} style={style} />;
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
      style={{ height: rowHeight(layout) }}
      className={`row${member ? ` group-member${member === "last" ? " group-last" : ""}` : ""}${isSelected ? " checked" : ""}${isFlash ? " flash" : ""}${r.archived ? " archived" : ""}`}
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
