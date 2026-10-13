/** The leaderboard's header row: sorting (a button per sortable column,
 *  `aria-sort` on its cell), column drag/resize, the column menu (their
 *  keyboard equivalents) and the select-all checkbox. */
import { useId, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { DATE_SORT_OF, EXPERIMENT_COL_INDEX, STICKY_BG, canShift, isPinned } from "./leaderboardColumns";
import ColumnMenu, { type MenuAction } from "./ColumnMenu";
import { HeaderCheckbox, ResizeGrip, type HeaderCheckProps } from "./LeaderboardHeadParts";
import { layoutIds, type RowLayout } from "./LeaderboardRow";
import HeadGroups, { GROUP_ROW_HEIGHT } from "./LeaderboardHeadGroups";
import { headGroups, isInnerRunId } from "./innerRunColumns";
import "./leaderboardHead.css";

export const TIMESTAMP_SORT = "timestamp";
export const IDX_SORT = "idx";
export type { HeaderCheckProps } from "./LeaderboardHeadParts";

/** What the header can change about the columns: widths and order (drag),
 *  and from the column menu, when given: move, hide and pin. */
export interface ColumnEdits {
  onResize: (id: string, width: number) => void;
  onMove: (from: string, to: string) => void;
  /** Move a column one place left (-1) or right (1). */
  onShift?: (id: string, delta: number) => void;
  /** Hide an `m:`/`p:`/`c:` column. */
  onHide?: (id: string) => void;
  /** Pin or unpin an `m:`/`p:` column. */
  onPin?: (id: string) => void;
  /** The pinned `m:`/`p:` columns. */
  pinned?: readonly string[];
}

export interface SortState {
  sort: string | null;
  /** The sorted column's direction (null: none sorted). */
  order: "asc" | "desc" | null;
  /** True when the current direction is the column's worst-first. */
  reversed: boolean;
  onSort: (col: string) => void;
}

/** Every header cell sticks to the top of the scroll container; cells whose
 *  body style already has `position: "sticky"` (experiment + pinned metric/
 *  param columns) sit at zIndex 3 so they aren't overlapped by other headers
 *  when both axes scroll simultaneously. */
function headStyle(style: CSSProperties, index: number, top = 0): CSSProperties {
  const base: CSSProperties = {
    ...style,
    position: "sticky",
    top,
    zIndex: 2,
    background: STICKY_BG,
  };
  if (index === EXPERIMENT_COL_INDEX) return { ...base, zIndex: 4 };
  return style.position === "sticky" ? { ...base, zIndex: 3 } : base;
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
  return { label: id.includes(":") ? name : id, sort: null };
}

const HEAD_CLASS: Record<string, string> = {
  check: "check-cell", idx: "num", status: "status-col-head", experiment: "exp-head", when: "num when-head",
};
const ARIA_SORT = { asc: "ascending", desc: "descending" } as const;
const plainName = (id: string) => (id === "idx" ? "#" : id.includes(":") ? id.slice(2) : id);
const hideable = (id: string) => /^[mpc]:/.test(id);
const pinnable = (id: string) => /^[mp]:/.test(id);

/** The column menu's entries for *id* (sort key *sort*). */
function menuActions(
  id: string, ids: readonly string[], sort: string | null, s: SortState, edits: ColumnEdits,
): MenuAction[] {
  const out: MenuAction[] = [];
  if (sort) out.push({ label: s.sort === sort ? "Reverse sort" : "Sort", run: () => s.onSort(sort) });
  const { onHide, onPin, onShift } = edits;
  if (onHide && hideable(id)) out.push({ label: "Hide column", run: () => onHide(id) });
  const pinned = new Set(edits.pinned);
  if (onPin && pinnable(id)) {
    out.push({ label: pinned.has(id) ? "Unpin column" : "Pin column", run: () => onPin(id) });
  }
  if (onShift && !isPinned(id)) {
    out.push(
      { label: "Move left", run: () => onShift(id, -1), disabled: !canShift(ids, id, -1, pinned) },
      { label: "Move right", run: () => onShift(id, 1), disabled: !canShift(ids, id, 1, pinned) },
    );
  }
  return out;
}

/** Enter and Space sort here, so a button's own click on them never runs too. */
const sortKeys = (onSort: () => void) => (e: KeyboardEvent) => {
  if (e.key !== "Enter" && e.key !== " ") return;
  e.preventDefault();
  onSort();
};

const headClass = (id: string) =>
  HEAD_CLASS[id] ?? (id.startsWith("c:") && id !== "c:tags" && id !== "c:comments" ? "num fleet-head" : id.startsWith("p:") ? "param-head" : "");

export default function Head({ layout, sort: s, edits, check }: {
  layout: RowLayout;
  sort: SortState;
  edits?: ColumnEdits;
  check?: HeaderCheckProps;
}) {
  const ids = layoutIds(layout);
  const groups = headGroups(ids);
  const helpId = useId();
  const top = groups ? GROUP_ROW_HEIGHT : 0;
  const headStyles = layout.styles.map((st, i) => headStyle(st, i, top));
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const arrow = (col: string) => (s.sort === col ? (s.reversed ? " ▴" : " ▾") : "");
  const ariaSort = (col: string) => (s.sort === col && s.order ? ARIA_SORT[s.order] : "none");
  return (
    <thead>
      {groups && <HeadGroups groups={groups} styles={layout.styles} helpId={helpId} />}
      <tr>
        {ids.map((id, i) => {
          const { label, sort, title } = headInfo(id, layout);
          const movable = Boolean(edits) && !isPinned(id);
          const inner = isInnerRunId(id);
          const actions = edits && id !== "check" ? menuActions(id, ids, sort, s, edits) : [];
          const cls = [
            headClass(id), sort && "sortable", sort && s.sort === sort && "sorted", actions.length && "has-menu",
            dragging === id && "col-dragging", over === id && dragging !== id && "col-drop",
          ].filter(Boolean).join(" ");
          return (
            <th
              key={id} data-col-id={id} style={headStyles[i]} className={cls || undefined}
              aria-sort={sort ? ariaSort(sort) : undefined}
              aria-describedby={inner ? helpId : undefined}
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
              {id === "check" && check ? <HeaderCheckbox {...check} />
                : sort ? (
                  // The cell's own click sorts, so a click anywhere in it does.
                  <button type="button" className="th-sort" aria-label={title} title={title} onKeyDown={sortKeys(() => s.onSort(sort))}>
                    {label}{arrow(sort)}
                  </button>
                ) : label}
              {actions.length > 0 && <ColumnMenu name={plainName(id)} actions={actions} />}
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
