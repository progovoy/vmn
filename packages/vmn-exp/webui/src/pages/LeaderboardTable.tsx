import {
  useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent,
  type MutableRefObject, type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { ExperimentRow } from "../types";
import { useScrollMemory } from "../hooks/useScrollMemory";
import { useRowKeys } from "../hooks/useRowKeys";
import {
  DATE_SORT_OF, EXPERIMENT_COL_INDEX, MIN_COL_WIDTH, STICKY_BG, isPinned,
} from "./leaderboardColumns";
import Row, { ROW_HEIGHT, layoutIds, type RowLayout } from "./LeaderboardRow";

/** Rows from the end at which the next page is requested. */
const NEAR_END_ROWS = 20;
const SKELETON_ROWS = 8;

export const TIMESTAMP_SORT = "timestamp";
export const IDX_SORT = "idx";

/** What the header can change about the columns: widths and order. */
export interface ColumnEdits {
  onResize: (id: string, width: number) => void;
  onMove: (from: string, to: string) => void;
}

export interface SortState {
  sort: string | null;
  /** True when the current direction is the column's worst-first. */
  reversed: boolean;
  onSort: (col: string) => void;
}

/** Every header cell sticks to the top of the scroll container; cells whose
 *  body style already has `position: "sticky"` (experiment + pinned metric/
 *  param columns) sit at zIndex 3 so they aren't overlapped by other headers
 *  when both axes scroll simultaneously. */
function headStyle(style: CSSProperties, index: number): CSSProperties {
  const base: CSSProperties = {
    ...style,
    position: "sticky",
    top: 0,
    zIndex: 2,
    background: STICKY_BG,
  };
  if (index === EXPERIMENT_COL_INDEX) return { ...base, zIndex: 4 };
  return style.position === "sticky" ? { ...base, zIndex: 3 } : base;
}

/** A drag grip on a header's right edge: dragging it resizes the column.
 *  The drag moves only the header's `<col>`; the width is kept (and the rows
 *  re-laid out) once, on release. */
function ResizeGrip({ width, onResize }: { width: number; onResize: (w: number) => void }) {
  const onMouseDown = (e: ReactMouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const th = (e.currentTarget as HTMLElement).closest("th")!;
    const col = th.closest("table")?.querySelectorAll("colgroup col")[th.cellIndex] as HTMLElement | undefined;
    const x0 = e.clientX;
    const widthAt = (ev: MouseEvent) => Math.max(MIN_COL_WIDTH, Math.round(width + ev.clientX - x0));
    const move = (ev: MouseEvent) => {
      const w = `${widthAt(ev)}px`;
      th.style.width = w;
      if (col) col.style.width = w;
    };
    const up = (ev: MouseEvent) => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      onResize(widthAt(ev));
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };
  return (
    <span
      className="col-resize" role="separator" aria-orientation="vertical" aria-label="resize column"
      onMouseDown={onMouseDown} onClick={(e) => e.stopPropagation()} draggable={false}
      onDragStart={(e) => { e.preventDefault(); e.stopPropagation(); }}
    />
  );
}

/** Header label and sort key per column id (null: not sortable). */
function headInfo(id: string, layout: RowLayout): { label: ReactNode; sort: string | null; title?: string } {
  const name = id.slice(2);
  if (id === "idx") return { label: "#", sort: IDX_SORT, title: "sort by run number (newest first)" };
  if (id === "when") return { label: "when", sort: TIMESTAMP_SORT, title: "sort by time (newest first)" };
  if (id in DATE_SORT_OF) return { label: name, sort: DATE_SORT_OF[id], title: `sort by ${name} time (newest first)` };
  if (id.startsWith("m:")) {
    const meta = layout.colMeta[name];
    return {
      label: (
        <>
          {name}{" "}
          {meta && meta.best !== null && <span className="goal">{meta.goal === "min" ? "↓" : "↑"}</span>}
        </>
      ),
      sort: name, title: `sort by ${name} (best first)`,
    };
  }
  if (id === "check") return { label: "", sort: null };
  if (id === "c:tags") return { label: "tags", sort: null };
  return { label: id.includes(":") ? name : id, sort: null };
}

const HEAD_CLASS: Record<string, string> = {
  check: "check-cell", idx: "num", experiment: "exp-head", when: "num when-head",
};
const headClass = (id: string) =>
  HEAD_CLASS[id] ?? (id.startsWith("c:") && id !== "c:tags" ? "num fleet-head" : id.startsWith("p:") ? "param-head" : "");

function Head({ layout, sort: s, edits }: { layout: RowLayout; sort: SortState; edits?: ColumnEdits }) {
  const headStyles = layout.styles.map(headStyle);
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const arrow = (col: string) => (s.sort === col ? (s.reversed ? " ▴" : " ▾") : "");
  return (
    <thead>
      <tr>
        {layoutIds(layout).map((id, i) => {
          const { label, sort, title } = headInfo(id, layout);
          const movable = Boolean(edits) && !isPinned(id);
          const cls = [
            headClass(id), sort && "sortable", sort && s.sort === sort && "sorted",
            dragging === id && "col-dragging", over === id && dragging !== id && "col-drop",
          ].filter(Boolean).join(" ");
          return (
            <th
              key={id} data-col-id={id} style={headStyles[i]} className={cls || undefined} title={title}
              onClick={sort ? () => s.onSort(sort) : undefined}
              draggable={movable}
              onDragStart={movable ? (e) => {
                setDragging(id);
                e.dataTransfer?.setData("text/plain", id);
                if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
              } : undefined}
              onDragOver={(e) => {
                if (!dragging || !movable) return;
                e.preventDefault();
                setOver(id);
              }}
              onDragLeave={() => setOver((o) => (o === id ? null : o))}
              onDrop={(e) => {
                e.preventDefault();
                if (dragging && movable) edits?.onMove(dragging, id);
                setDragging(null);
                setOver(null);
              }}
              onDragEnd={() => { setDragging(null); setOver(null); }}
            >
              {label}{sort && arrow(sort)}
              {edits && (
                <ResizeGrip width={layout.widths?.[i] ?? 0} onResize={(w) => edits.onResize(id, w)} />
              )}
            </th>
          );
        })}
      </tr>
    </thead>
  );
}

function SkeletonRows({ layout }: { layout: RowLayout }) {
  return (
    <>
      {Array.from({ length: SKELETON_ROWS }, (_, i) => (
        <tr key={i} className="skeleton-row" style={{ height: ROW_HEIGHT }}>
          {layout.styles.map((st, c) => (
            <td key={c} style={st}><span className="skel-bar" /></td>
          ))}
        </tr>
      ))}
    </>
  );
}

export default function LeaderboardTable({
  rows, layout, sort, selected, flash, onToggle, onPrefetch, hasMore, onNearEnd, visibleRef,
  collapsedOf, onFold, edits, onFit,
}: {
  /** Undefined while the first page loads: skeleton rows under a live header. */
  rows: ExperimentRow[] | undefined;
  layout: RowLayout;
  sort: SortState;
  selected: ReadonlySet<string>;
  flash: string | null;
  onToggle: (verstr: string, range: boolean) => void;
  onPrefetch: (verstr: string) => void;
  /** Whether an outer run is shut (null: not an outer run). */
  collapsedOf: (r: ExperimentRow) => boolean | null;
  onFold: (r: ExperimentRow) => void;
  hasMore: boolean;
  onNearEnd: () => void;
  visibleRef: MutableRefObject<() => string[]>;
  /** Column resizing/reordering; the header is fixed when omitted. */
  edits?: ColumnEdits;
  /** Told the width (px) the table has to fill, and again when it changes. */
  onFit?: (width: number) => void;
}) {
  const parentRef = useRef<HTMLDivElement>(null);
  const scroll = useScrollMemory();
  const list = rows ?? [];
  const virtualizer = useVirtualizer({
    count: list.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 20,
    initialOffset: scroll.initial,
  });
  const items = virtualizer.getVirtualItems();
  const navigate = useNavigate();
  const keys = useRowKeys(parentRef, list.length, (i) => virtualizer.scrollToIndex?.(i), navigate);
  visibleRef.current = () => items.map((it) => list[it.index]?.verstr).filter(Boolean);

  // Back to this entry: put the table where it was once its rows are there.
  const restored = useRef(false);
  useLayoutEffect(() => {
    if (restored.current || !rows?.length || !parentRef.current) return;
    restored.current = true;
    if (scroll.initial) parentRef.current.scrollTop = scroll.initial;
  }, [rows, scroll.initial]);

  useEffect(() => {
    const el = parentRef.current;
    if (!el || !onFit) return;
    const ro = new ResizeObserver((entries) => onFit(Math.floor(entries[0].contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [onFit]);

  const onScroll = () => {
    const el = parentRef.current;
    if (!el) return;
    scroll.save(el.scrollTop);
    const nearEnd = el.scrollTop + el.clientHeight >= el.scrollHeight - NEAR_END_ROWS * ROW_HEIGHT;
    if (nearEnd && hasMore) onNearEnd();
  };

  return (
    <div className="card flush">
      <div
        className="tbl-scroll"
        ref={parentRef}
        onScroll={onScroll}
        onKeyDown={keys.onKeyDown}
        style={{ maxHeight: "calc(100vh - 340px)", overflow: "auto" }}
      >
        <table
          role="grid" aria-label="experiments" className="lb-table"
          style={{ tableLayout: "fixed", width: layout.total }}
        >
          <colgroup>{layout.styles.map((st, i) => <col key={i} style={{ width: st.width }} />)}</colgroup>
          <Head layout={layout} sort={sort} edits={edits} />
          {rows === undefined ? (
            <tbody><SkeletonRows layout={layout} /></tbody>
          ) : (
            <tbody>
              {items.length > 0 && items[0].start > 0 && (
                <tr aria-hidden style={{ height: items[0].start }} />
              )}
              {items.map((it) => {
                const r = list[it.index];
                return (
                  <Row
                    key={r.verstr}
                    row={r}
                    index={it.index}
                    isActive={it.index === keys.active}
                    collapsed={collapsedOf(r)}
                    onFold={onFold}
                    isSelected={selected.has(r.verstr)}
                    isFlash={flash === r.verstr}
                    layout={layout}
                    onToggle={onToggle}
                    onPrefetch={onPrefetch}
                  />
                );
              })}
              {items.length > 0 && virtualizer.getTotalSize() > items[items.length - 1].end && (
                <tr aria-hidden style={{ height: virtualizer.getTotalSize() - items[items.length - 1].end }} />
              )}
            </tbody>
          )}
        </table>
      </div>
    </div>
  );
}
