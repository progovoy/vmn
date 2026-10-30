/** The Jobs view's grid (plan 23 W1): virtualized like the board, its
 *  headers sorting by the job sort keys, the board's keys (useRowKeys) and
 *  density; grouped, a header row per group of jobs. Below 640px, cards. */
import { useMemo, useRef, type CSSProperties, type MutableRefObject } from "react";
import { useFillHeight } from "../../hooks/useFillHeight";
import { useNavigate } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { HeaderCheck } from "../../hooks/useBoardSelection";
import type { BoardViewport } from "../../hooks/useLeaderboardRows";
import { useHeldViewport } from "../../components/NewRowsBar";
import { useRowKeys } from "../../hooks/useRowKeys";
import { useScrollMemory } from "../../hooks/useScrollMemory";
import { NARROW_QUERY, useMediaQuery } from "../../hooks/useMediaQuery";
import type { Density } from "../../util/density";
import { boardRows, isGroupItem, type BoardItem } from "../../util/groupItems";
import { STICKY_BG } from "../leaderboardColumns";
import type { GroupFilter } from "../LeaderboardTable";
import { ARIA_SORT, HeaderCheckbox, SortButton, type HeaderCheckProps } from "../LeaderboardHeadParts";
import type { JobContext } from "./JobCells";
import JobCards from "./JobCards";
import JobRow from "./JobRow";
import { densityRowHeight } from "../LeaderboardRow";
import { JobGroupRow, JobMoreRow } from "./JobGroupRows";
import { COLUMN_STYLES, JOBS_WIDTH, JOB_COLUMNS, type Order } from "./jobColumns";
import { JobsTreeSlot, SLOT_HEIGHT, isTreeSlot, useTreeSlots } from "./JobsTreeSlot";
import "../leaderboardTable.css";
import "./jobsTable.css";

const NEAR_END_ROWS = 20;
const SKELETON_ROWS = 8;
const CARDS_REFRESHED = 40;
const NO_ITEMS: BoardItem[] = [];
const HEAD_STYLES: readonly CSSProperties[] = COLUMN_STYLES.map((st) => ({
  ...st, position: "sticky", top: 0, zIndex: 2, background: STICKY_BG,
}));

export interface JobsSort {
  sort: string;
  order: Order;
  onSort: (sort: string) => void;
}

export interface JobGroupActions {
  /** What a group counts: `job`, `run`. */
  noun: string;
  /** A group too big to unfold opens as its clause (plan 23 §3.4). */
  asFilter?: GroupFilter;
  onFold: (key: string) => void;
  onMore: (key: string) => void;
  checkOf: (verstrs: readonly string[]) => HeaderCheck;
  onCheck: (verstrs: readonly string[]) => void;
}

export interface JobsTableProps {
  items: BoardItem[] | undefined;
  ctx: JobContext;
  sort: JobsSort;
  selected: ReadonlySet<string>;
  density: Density;
  headerCheck: HeaderCheckProps;
  groups: JobGroupActions;
  hasMore: boolean;
  onNearEnd: () => void;
  visibleRef: MutableRefObject<() => string[]>;
  /** Told whether the reader is scrolled down or selecting (plan 23 W6). */
  viewportRef?: MutableRefObject<BoardViewport>;
  onToggle: (verstr: string, range: boolean) => void;
  onClearAnchor: () => void;
  /** Said in place of the rows when there are none. */
  emptyText: string;
  /** Where an outer run's tree reads its children; none: rows have no expander. */
  trees?: { ws: string; app: string };
}

export default function JobsTable(props: JobsTableProps) {
  const narrow = useMediaQuery(NARROW_QUERY);
  const { items } = props;
  const rows = useMemo(() => (narrow ? boardRows(items ?? []) : []), [narrow, items]);
  // The phone's cards scroll the window; the grid its own element.
  const windowScroll = useRef<HTMLElement | null>(null);
  useHeldViewport(narrow ? props.viewportRef : undefined, windowScroll, props.selected);
  if (!narrow) return <JobsGrid {...props} />;
  props.visibleRef.current = () => rows.slice(0, CARDS_REFRESHED).map((r) => r.verstr);
  return <JobCards {...props} />;
}

function Head({ sort, check }: { sort: JobsSort; check: HeaderCheckProps }) {
  return (
    <thead>
      <tr>
        {JOB_COLUMNS.map((c, i) => {
          const sorted = c.sort === sort.sort;
          return (
            <th
              key={c.id} data-col-id={c.id} style={HEAD_STYLES[i]}
              className={[c.numeric && "num", c.sort && "sortable", sorted && "sorted", c.id === "check" && "check-cell"].filter(Boolean).join(" ") || undefined}
              aria-sort={c.sort ? (sorted ? ARIA_SORT[sort.order] : "none") : undefined}
              onClick={c.sort ? () => sort.onSort(c.sort!) : undefined}
            >
              {c.id === "check" ? <HeaderCheckbox {...check} />
                : c.sort ? (
                  <SortButton title={c.title} onSort={() => sort.onSort(c.sort!)}>
                    {c.label}{sorted ? (sort.order === "asc" ? " ▴" : " ▾") : ""}
                  </SortButton>
                ) : c.label}
            </th>
          );
        })}
      </tr>
    </thead>
  );
}

function JobsGrid({
  items, ctx, sort, selected, density, headerCheck, groups, hasMore, onNearEnd, visibleRef,
  onToggle, onClearAnchor, emptyText, viewportRef, trees,
}: JobsTableProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  useFillHeight(parentRef);
  useHeldViewport(viewportRef, parentRef, selected);
  const scroll = useScrollMemory();
  const slots = useTreeSlots(items ?? NO_ITEMS);
  const list = slots.list;
  const height = densityRowHeight(density);
  const virtualizer = useVirtualizer({
    count: list.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (i) => (isTreeSlot(list[i]) ? SLOT_HEIGHT : height),
    overscan: 20,
    initialOffset: scroll.initial,
  });
  const virtual = virtualizer.getVirtualItems();
  const navigate = useNavigate();
  const keys = useRowKeys(parentRef, list.length, (i) => virtualizer.scrollToIndex?.(i), {
    open: navigate,
    toggle: (i, range) => {
      const it = list[i];
      if (isTreeSlot(it)) return;
      if (!isGroupItem(it)) onToggle(it.verstr, range);
      else if (it.item === "group" && it.rows.length) groups.onCheck(it.rows);
    },
    clearAnchor: onClearAnchor,
  });
  visibleRef.current = () =>
    virtual.map((v) => list[v.index]).flatMap((r) => (r && !isTreeSlot(r) && !isGroupItem(r) ? [r.verstr] : []));

  const onScroll = () => {
    const el = parentRef.current;
    if (!el) return;
    scroll.save(el.scrollTop);
    if (hasMore && el.scrollTop + el.clientHeight >= el.scrollHeight - NEAR_END_ROWS * height) onNearEnd();
  };
  const last = virtual[virtual.length - 1];

  return (
    <div className="card flush lb-card jobs-card">
      <div className="tbl-scroll" ref={parentRef} onScroll={onScroll} style={{ maxHeight: "calc(100vh - 340px)", overflow: "auto" }}>
        <table
          role="grid" aria-label="outer runs"
          className={`lb-table jobs-table${density === "compact" ? " compact" : ""}`}
          style={{ tableLayout: "fixed", width: JOBS_WIDTH }}
        >
          <colgroup>{JOB_COLUMNS.map((c, i) => <col key={c.id} style={COLUMN_STYLES[i]} />)}</colgroup>
          <Head sort={sort} check={headerCheck} />
          <tbody>
            {items === undefined && Array.from({ length: SKELETON_ROWS }, (_, i) => (
              <tr key={i} className="skeleton-row" style={{ height }}>
                {JOB_COLUMNS.map((c) => <td key={c.id}><span className="skel-bar" /></td>)}
              </tr>
            ))}
            {items?.length === 0 && (
              <tr className="jobs-empty"><td colSpan={JOB_COLUMNS.length}>{emptyText}</td></tr>
            )}
            {virtual.length > 0 && virtual[0].start > 0 && <tr aria-hidden style={{ height: virtual[0].start }} />}
            {virtual.map((v) => {
              const it = list[v.index];
              const active = v.index === keys.active;
              if (isTreeSlot(it)) {
                return trees && (
                  <JobsTreeSlot
                    key={`tree:${it.row.verstr}`} slot={it} ws={trees.ws} app={trees.app} ctx={ctx}
                    index={v.index} measure={virtualizer.measureElement}
                  />
                );
              }
              if (isGroupItem(it)) {
                return it.item === "more"
                  ? <JobMoreRow key={`more:${it.key}`} item={it} index={v.index} isActive={active} height={height} onMore={groups.onMore} />
                  : (
                    <JobGroupRow
                      key={`group:${it.group.key}`} item={it} index={v.index} isActive={active} height={height}
                      onFold={groups.onFold} asFilter={groups.asFilter} noun={groups.noun} check={{ state: groups.checkOf(it.rows), onToggle: () => groups.onCheck(it.rows) }}
                    />
                  );
              }
              return (
                <JobRow
                  key={it.verstr} r={it} index={v.index} isActive={active}
                  isSelected={selected.has(it.verstr)}
                  density={density} ctx={ctx} onToggle={onToggle}
                  expanded={slots.open.has(it.verstr)} onExpand={trees ? slots.toggle : undefined}
                />
              );
            })}
            {last && virtualizer.getTotalSize() > last.end && (
              <tr aria-hidden style={{ height: virtualizer.getTotalSize() - last.end }} />
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
