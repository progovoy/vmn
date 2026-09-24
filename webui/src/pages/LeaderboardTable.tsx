import { useLayoutEffect, useRef, type CSSProperties, type MutableRefObject } from "react";
import { useNavigate } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { ExperimentRow } from "../types";
import { useScrollMemory } from "../hooks/useScrollMemory";
import { useRowKeys } from "../hooks/useRowKeys";
import { EXPERIMENT_COL_INDEX, STICKY_BG } from "./leaderboardColumns";
import Row, { type RowLayout } from "./LeaderboardRow";

const ROW_HEIGHT = 48;
/** Rows from the end at which the next page is requested. */
const NEAR_END_ROWS = 20;
const SKELETON_ROWS = 8;

export const TIMESTAMP_SORT = "timestamp";

export interface SortState {
  sort: string | null;
  /** True when the current direction is the column's worst-first. */
  reversed: boolean;
  onSort: (col: string) => void;
}

/** Every header cell sticks to the top of the scroll container; the
 *  experiment column additionally stays pinned to the left (it already
 *  carries the sticky-left style from `columnStyles`) and sits above the
 *  other header cells so it isn't overlapped once they scroll under it. */
function headStyle(style: CSSProperties, index: number): CSSProperties {
  const base: CSSProperties = {
    ...style,
    position: "sticky",
    top: 0,
    zIndex: 2,
    background: STICKY_BG,
  };
  return index === EXPERIMENT_COL_INDEX ? { ...base, zIndex: 3 } : base;
}

function Head({ layout, sort: s }: { layout: RowLayout; sort: SortState }) {
  const { styles, metricCols, paramCols, colMeta, paramBase, tagsIdx, noteIdx } = layout;
  const headStyles = styles.map(headStyle);
  const arrow = (col: string) => (s.sort === col ? (s.reversed ? " ▴" : " ▾") : "");
  return (
    <thead>
      <tr>
        <th style={headStyles[0]} className="check-cell"></th>
        <th style={headStyles[1]}>#</th>
        <th style={headStyles[2]}>status</th>
        <th style={headStyles[EXPERIMENT_COL_INDEX]} className="exp-head">experiment</th>
        {metricCols.map((m, i) => (
          <th
            key={m}
            style={headStyles[4 + i]}
            className={`sortable${s.sort === m ? " sorted" : ""}`}
            onClick={() => s.onSort(m)}
            title={`sort by ${m} (best first)`}
          >
            {m}{" "}
            {colMeta[m].best !== null && (
              <span className="goal">{colMeta[m].goal === "min" ? "↓" : "↑"}</span>
            )}
            {arrow(m)}
          </th>
        ))}
        {paramCols.map((p, i) => (
          <th key={`p-${p}`} className="param-head" style={headStyles[paramBase + i]}>{p}</th>
        ))}
        {tagsIdx !== null && <th style={headStyles[tagsIdx]}>tags</th>}
        <th style={headStyles[noteIdx]}>note</th>
        <th
          className={`num sortable when-head${s.sort === TIMESTAMP_SORT ? " sorted" : ""}`}
          style={headStyles[noteIdx + 1]}
          onClick={() => s.onSort(TIMESTAMP_SORT)}
          title="sort by time (newest first)"
        >
          when{arrow(TIMESTAMP_SORT)}
        </th>
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
  collapsedOf, onFold,
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
        <table role="grid" aria-label="experiments" style={{ tableLayout: "fixed", width: layout.total }}>
          <Head layout={layout} sort={sort} />
          {rows === undefined ? (
            <tbody><SkeletonRows layout={layout} /></tbody>
          ) : (
            <tbody style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
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
                    start={it.start}
                    size={it.size}
                    isSelected={selected.has(r.verstr)}
                    isFlash={flash === r.verstr}
                    layout={layout}
                    onToggle={onToggle}
                    onPrefetch={onPrefetch}
                  />
                );
              })}
            </tbody>
          )}
        </table>
      </div>
    </div>
  );
}
