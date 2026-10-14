import { useEffect, useLayoutEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { useNavigate } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { GroupAggregate } from "../apiGroups";
import type { HeaderCheck } from "../hooks/useBoardSelection";
import { boardRows, isGroupItem, memberPlaces, type BoardGroup, type BoardItem } from "../util/groupItems";
import { useScrollMemory } from "../hooks/useScrollMemory";
import { useRowKeys } from "../hooks/useRowKeys";
import { useMoreRight } from "../hooks/useMoreRight";
import { NARROW_QUERY, useMediaQuery } from "../hooks/useMediaQuery";
import type { BoardViewport } from "../hooks/useLeaderboardRows";
import { useHeldViewport } from "../components/NewRowsBar";
import LeaderboardCards from "./LeaderboardCards";
import Row, { rowHeight, type RowLayout } from "./LeaderboardRow";
import { GroupHeaderRow, GroupMoreRow } from "./LeaderboardGroupRow";
import Head, { type ColumnEdits, type HeaderCheckProps, type SortState } from "./LeaderboardHead";
import { visibleColumns, windowLayout, type ColRange } from "./columnWindow";
import type { Density } from "../util/density";
import "./leaderboardTable.css";

export { IDX_SORT, TIMESTAMP_SORT, type ColumnEdits, type SortState } from "./LeaderboardHead";

/** Rows from the end at which the next page is requested. */
const NEAR_END_ROWS = 20;
const SKELETON_ROWS = 8;

function SkeletonRows({ layout }: { layout: RowLayout }) {
  return (
    <>
      {Array.from({ length: SKELETON_ROWS }, (_, i) => (
        <tr key={i} className="skeleton-row" style={{ height: rowHeight(layout) }}>
          {layout.styles.map((st, c) => (
            <td key={c} style={st}><span className="skel-bar" /></td>
          ))}
        </tr>
      ))}
    </>
  );
}

type TableProps = {
  /** Undefined while the first page loads: skeleton rows under a live header. */
  rows: BoardItem[] | undefined;
  layout: RowLayout;
  sort: SortState;
  selected: ReadonlySet<string>;
  flash: string | null;
  onToggle: (verstr: string, range: boolean) => void;
  /** The header checkbox over the rows on screen; none when omitted. */
  headerCheck?: HeaderCheckProps;
  onPrefetch: (verstr: string) => void;
  /** Set while the board is grouped (plan 22 G4): the aggregate its header
   *  rows show, folding a group, and loading a group's other rows. */
  groups?: GroupActions;
  hasMore: boolean;
  onNearEnd: () => void;
  visibleRef: MutableRefObject<() => string[]>;
  /** Told whether the reader is scrolled down or selecting (plan 23 W6). */
  viewportRef?: MutableRefObject<BoardViewport>;
  /** Column resizing/reordering; the header is fixed when omitted. */
  edits?: ColumnEdits;
  /** Told the width (px) the table has to fill, and again when it changes. */
  onFit?: (width: number) => void;
  /** The id of the element describing the board (its caption). */
  describedBy?: string;
  /** Comfortable when omitted; the phone's cards have one density. */
  density?: Density;
  /** Escape on the board: forget the last toggled row. */
  onClearAnchor?: () => void;
};

export interface GroupActions {
  /** The grouping (`group=`). */
  field: string;
  aggregate: GroupAggregate;
  onFold: (key: string) => void;
  onMore: (key: string) => void;
  /** A group header's checkbox over its rows (plan 22 G7). */
  checkOf: (verstrs: readonly string[]) => HeaderCheck;
  onCheck: (verstrs: readonly string[]) => void;
  /** A group too big to unfold opens as its clause (plan 23 §3.4). */
  asFilter?: GroupFilter;
}

export interface GroupFilter {
  clauseOf: (g: BoardGroup) => string | null;
  onFilter: (clause: string) => void;
}

/** Cards that refresh with the board: about a phone screen's worth and the
 *  scroll ahead of it, like the grid's virtual window. */
const CARDS_REFRESHED = 40;

/** The grid, or below 640px one card per run (plan 20 C8). */
export default function LeaderboardTable(props: TableProps) {
  const narrow = useMediaQuery(NARROW_QUERY);
  // The phone's cards scroll the window; the grid its own element.
  const windowScroll = useRef<HTMLElement | null>(null);
  useHeldViewport(narrow ? props.viewportRef : undefined, windowScroll, props.selected);
  if (!narrow) return <GridTable {...props} />;
  const { rows, visibleRef } = props;
  visibleRef.current = () => boardRows(rows ?? []).map((r) => r.verstr).slice(0, CARDS_REFRESHED);
  return <LeaderboardCards {...props} />;
}

const sameRange = (a: ColRange | null, b: ColRange | null) =>
  a === b || (a !== null && b !== null && a.start === b.start && a.end === b.end);

/** The columns to render at the scroll element's horizontal position. */
function columnsAt(full: RowLayout, el: HTMLElement | null): ColRange | null {
  return visibleColumns(full, el?.scrollLeft ?? 0, el?.clientWidth || window.innerWidth);
}

function GridTable({
  rows, layout: full, sort, selected, flash, onToggle, headerCheck, onPrefetch, hasMore, onNearEnd, visibleRef,
  groups, edits, onFit, describedBy, density, onClearAnchor, viewportRef,
}: TableProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  useHeldViewport(viewportRef, parentRef, selected);
  const [cols, setCols] = useState<ColRange | null>(() => columnsAt(full, null));
  useLayoutEffect(() => {
    setCols((was) => {
      const now = columnsAt(full, parentRef.current);
      return sameRange(was, now) ? was : now;
    });
  }, [full]);
  const layout = useMemo(() => ({ ...windowLayout(full, cols), density }), [full, cols, density]);
  const scroll = useScrollMemory();
  const list = rows ?? [];
  const places = useMemo(() => memberPlaces(list), [list]);
  const virtualizer = useVirtualizer({
    count: list.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight(layout),
    overscan: 20,
    initialOffset: scroll.initial,
  });
  const items = virtualizer.getVirtualItems();
  const navigate = useNavigate();
  const keys = useRowKeys(parentRef, list.length, (i) => virtualizer.scrollToIndex?.(i), {
    open: navigate,
    toggle: (i, range) => {
      const it = list[i];
      if (!isGroupItem(it)) onToggle(it.verstr, range);
      else if (it.item === "group" && it.rows.length) groups?.onCheck(it.rows);
    },
    clearAnchor: () => onClearAnchor?.(),
  });
  visibleRef.current = () =>
    items.map((it) => list[it.index]).flatMap((r) => (r && !isGroupItem(r) ? [r.verstr] : []));

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

  const edge = useMoreRight(parentRef, layout.total);
  const onScroll = () => {
    const el = parentRef.current;
    if (!el) return;
    edge.check();
    scroll.save(el.scrollTop);
    const now = columnsAt(full, el);
    if (!sameRange(cols, now)) setCols(now);
    const nearEnd = el.scrollTop + el.clientHeight >= el.scrollHeight - NEAR_END_ROWS * rowHeight(layout);
    if (nearEnd && hasMore) onNearEnd();
  };

  return (
    <div className={`card flush lb-card${edge.more ? " more-right" : ""}`}>
      {/* A fade over the right edge while columns run past it. */}
      <div className="lb-edge-fade" aria-hidden="true" />
      <div
        className="tbl-scroll"
        ref={parentRef}
        onScroll={onScroll}
        style={{ maxHeight: "calc(100vh - 340px)", overflow: "auto" }}
      >
        <table
          role="grid" aria-label="experiments" aria-describedby={describedBy}
          className={`lb-table${density === "compact" ? " compact" : ""}`}
          style={{ tableLayout: "fixed", width: layout.total }}
        >
          <colgroup>{layout.styles.map((st, i) => <col key={i} style={{ width: st.width }} />)}</colgroup>
          <Head layout={layout} sort={sort} edits={edits} check={headerCheck} aggregate={groups?.aggregate} />
          {rows === undefined ? (
            <tbody><SkeletonRows layout={layout} /></tbody>
          ) : (
            <tbody>
              {items.length > 0 && items[0].start > 0 && (
                <tr aria-hidden style={{ height: items[0].start }} />
              )}
              {items.map((it) => {
                const r = list[it.index];
                if (isGroupItem(r)) {
                  if (r.item === "more") {
                    return <GroupMoreRow key={`more:${r.key}`} item={r} index={it.index} isActive={it.index === keys.active} layout={layout} onMore={groups!.onMore} member={places.get(it.index)} />;
                  }
                  const next = list[it.index + 1];
                  return (
                    <GroupHeaderRow
                      key={`group:${r.group.key}`} item={r} index={it.index} isActive={it.index === keys.active}
                      layout={layout} agg={groups!.aggregate} onFold={groups!.onFold}
                      check={{ state: groups!.checkOf(r.rows), onToggle: () => groups!.onCheck(r.rows) }}
                      asFilter={groups!.asFilter}
                      first={groups!.field === "code_verstr" && next && !isGroupItem(next) ? next : undefined}
                    />
                  );
                }
                return (
                  <Row
                    key={r.verstr}
                    row={r}
                    index={it.index}
                    isActive={it.index === keys.active}
                    isSelected={selected.has(r.verstr)}
                    isFlash={flash === r.verstr}
                    member={places.get(it.index)}
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
