/** The header cell's own controls: the sort button, the resize grip and the
 *  select-all box. */
import { useEffect, useRef, type KeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import type { HeaderCheck } from "../hooks/useBoardSelection";
import { MIN_COL_WIDTH } from "./leaderboardColumns";
import "./sortButton.css";

export const ARIA_SORT = { asc: "ascending", desc: "descending" } as const;

/** Enter and Space sort here, so a button's own click on them never runs too. */
const sortKeys = (onSort: () => void) => (e: KeyboardEvent) => {
  if (e.key !== "Enter" && e.key !== " ") return;
  e.preventDefault();
  onSort();
};

/** A sortable header's label: a button (keyboard + screen readers) drawn as
 *  header text. A click bubbles to the cell, whose own click sorts; the
 *  cell carries `aria-sort`. */
export function SortButton({ title, onSort, children }: { title?: string; onSort: () => void; children: ReactNode }) {
  return (
    <button type="button" className="th-sort" aria-label={title} title={title} onKeyDown={sortKeys(onSort)}>
      {children}
    </button>
  );
}

/** A drag grip on a header's right edge: dragging it resizes the column.
 *  The drag moves only the header's `<col>`; the width is kept (and the rows
 *  re-laid out) once, on release. */
export function ResizeGrip({ width, onResize }: { width: number; onResize: (w: number) => void }) {
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

/** The header checkbox: how many rows on screen are selected, and its click. */
export interface HeaderCheckProps {
  state: HeaderCheck;
  onToggle: () => void;
}

/** The header's select-all box: checked when every row on screen is
 *  selected, indeterminate when only some are. */
export function HeaderCheckbox({ state, onToggle }: HeaderCheckProps) {
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
