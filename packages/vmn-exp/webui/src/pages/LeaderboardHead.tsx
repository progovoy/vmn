/** The leaderboard's header row: sorting, column drag/resize and the
 *  select-all checkbox. */
import { useEffect, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import type { HeaderCheck } from "../hooks/useBoardSelection";
import { DATE_SORT_OF, EXPERIMENT_COL_INDEX, MIN_COL_WIDTH, STICKY_BG, isPinned } from "./leaderboardColumns";
import { layoutIds, type RowLayout } from "./LeaderboardRow";
import { INNER_RUNS_HELP, isInnerRunId } from "./innerRunColumns";

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
    const hasGoal = meta && meta.goal !== null;
    return {
      label: (
        <>
          {name}{" "}
          {hasGoal && meta.best !== null && <span className="goal">{meta.goal === "min" ? "↓" : "↑"}</span>}
        </>
      ),
      sort: name, title: hasGoal ? `sort by ${name} (best first)` : `sort by ${name} (high first)`,
    };
  }
  if (id === "check") return { label: "", sort: null };
  if (id === "c:tags") return { label: "tags", sort: null };
  if (id === "c:comments") return { label: "comments", sort: null };
  if (isInnerRunId(id)) return { label: "inner", sort: null, title: INNER_RUNS_HELP };
  return { label: id.includes(":") ? name : id, sort: null };
}

const HEAD_CLASS: Record<string, string> = {
  check: "check-cell", idx: "num", status: "status-col-head", experiment: "exp-head", when: "num when-head",
  "c:tags": "", "c:comments": "", "c:inner": "inner-head",
};
const headClass = (id: string) =>
  HEAD_CLASS[id] ?? (id.startsWith("c:") ? "num fleet-head" : id.startsWith("p:") ? "param-head" : "");

/** The header checkbox: how many rows on screen are selected, and its click. */
export interface HeaderCheckProps {
  state: HeaderCheck;
  onToggle: () => void;
}

/** The header's select-all box: checked when every row on screen is
 *  selected, indeterminate when only some are. */
function HeaderCheckbox({ state, onToggle }: HeaderCheckProps) {
  const ref = useRef<HTMLInputElement>(null);
  // Every render: a click clears the DOM flag even when the state stays put.
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = state === "some";
  });
  return (
    <input
      ref={ref} type="checkbox" aria-label="Select all visible runs"
      checked={state === "all"} onChange={onToggle}
    />
  );
}

export default function Head({ layout, sort: s, edits, check }: {
  layout: RowLayout;
  sort: SortState;
  edits?: ColumnEdits;
  check?: HeaderCheckProps;
}) {
  const ids = layoutIds(layout);
  const headStyles = layout.styles.map((st, i) => headStyle(st, i));
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const arrow = (col: string) => (s.sort === col ? (s.reversed ? " ▴" : " ▾") : "");
  return (
    <thead>
      <tr>
        {ids.map((id, i) => {
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
              {id === "check" && check ? <HeaderCheckbox {...check} /> : label}{sort && arrow(sort)}
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
