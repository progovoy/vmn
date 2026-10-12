import { useEffect, useLayoutEffect, useRef, type MutableRefObject } from "react";
import { useNavigate } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { ExperimentRow } from "../types";
import { useScrollMemory } from "../hooks/useScrollMemory";
import { useRowKeys } from "../hooks/useRowKeys";
import Row, { ROW_HEIGHT, type RowLayout } from "./LeaderboardRow";
import Head, { type ColumnEdits, type HeaderCheckProps, type SortState } from "./LeaderboardHead";

export { IDX_SORT, TIMESTAMP_SORT, type ColumnEdits, type SortState } from "./LeaderboardHead";

/** Rows from the end at which the next page is requested. */
const NEAR_END_ROWS = 20;
const SKELETON_ROWS = 8;

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
  rows, layout, sort, selected, flash, onToggle, headerCheck, onPrefetch, hasMore, onNearEnd, visibleRef,
  collapsedOf, onFold, edits, onFit,
}: {
  /** Undefined while the first page loads: skeleton rows under a live header. */
  rows: ExperimentRow[] | undefined;
  layout: RowLayout;
  sort: SortState;
  selected: ReadonlySet<string>;
  flash: string | null;
  onToggle: (verstr: string, range: boolean) => void;
  /** The header checkbox over the rows on screen; none when omitted. */
  headerCheck?: HeaderCheckProps;
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
          <Head layout={layout} sort={sort} edits={edits} check={headerCheck} />
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
