import { useEffect, useRef } from "react";
import type { ColumnCell } from "../pages/leaderboardColumns";

/** Full key from a cell: e.g. "m:lr" or "p:batch". */
function cellKey(c: ColumnCell): string {
  return `${c.kind === "metric" ? "m" : "p"}:${c.key}`;
}

/** Reorder/pin controls for leaderboard metric+param columns.
 *
 *  Columns are shown in their current display order (pinned group first, then
 *  unpinned). Each row has move-up / move-down buttons that are disabled at
 *  group edges, and a pin-toggle button with aria-pressed. Focus follows the
 *  moved item after a move. */
export default function ColumnOrderSection({
  cells,
  pinned,
  onMoveColumn,
  onTogglePin,
}: {
  cells: readonly ColumnCell[];
  pinned: readonly string[];
  onMoveColumn: (key: string, delta: number) => void;
  onTogglePin: (key: string) => void;
}) {
  if (cells.length === 0) return null;

  const pinnedSet = new Set(pinned);
  const pinnedCells = cells.filter((c) => pinnedSet.has(cellKey(c)));
  const unpinnedCells = cells.filter((c) => !pinnedSet.has(cellKey(c)));

  return (
    <div className="col-order-section">
      <div className="col-picker-section-head">
        <span className="col-picker-title">order</span>
      </div>
      <Group cells={pinnedCells} pinned={pinnedSet} onMove={onMoveColumn} onPin={onTogglePin} />
      <Group cells={unpinnedCells} pinned={pinnedSet} onMove={onMoveColumn} onPin={onTogglePin} />
    </div>
  );
}

function Group({
  cells, pinned, onMove, onPin,
}: {
  cells: readonly ColumnCell[];
  pinned: ReadonlySet<string>;
  onMove: (key: string, delta: number) => void;
  onPin: (key: string) => void;
}) {
  if (cells.length === 0) return null;

  // After a move, focus the moved item's button once cells update.
  // Using a ref avoids triggering a re-render just for focus tracking.
  const pendingFocus = useRef<{ key: string; dir: "up" | "down" } | null>(null);
  const btnRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  useEffect(() => {
    if (!pendingFocus.current) return;
    const { key, dir } = pendingFocus.current;
    pendingFocus.current = null;
    // Prefer the same direction; fall back to the other if that one is disabled.
    const other = dir === "up" ? "down" : "up";
    const preferred = btnRefs.current.get(`${key}-${dir}`);
    const fallback = btnRefs.current.get(`${key}-${other}`);
    const btn = preferred && !preferred.disabled ? preferred : fallback;
    btn?.focus();
  }, [cells]);

  return (
    <>
      {cells.map((cell, idx) => {
        const key = cellKey(cell);
        const isPinned = pinned.has(key);
        const isFirst = idx === 0;
        const isLast = idx === cells.length - 1;

        const setRef = (dir: "up" | "down") => (el: HTMLButtonElement | null) => {
          if (el) btnRefs.current.set(`${key}-${dir}`, el);
          else btnRefs.current.delete(`${key}-${dir}`);
        };

        return (
          <div key={key} className="col-order-row">
            <button
              type="button"
              ref={setRef("up")}
              aria-label={`Move ${cell.key} up`}
              disabled={isFirst}
              onClick={() => {
                pendingFocus.current = { key, dir: "up" };
                onMove(key, -1);
              }}
            >
              ▲
            </button>
            <button
              type="button"
              ref={setRef("down")}
              aria-label={`Move ${cell.key} down`}
              disabled={isLast}
              onClick={() => {
                pendingFocus.current = { key, dir: "down" };
                onMove(key, 1);
              }}
            >
              ▼
            </button>
            <button
              type="button"
              aria-label={`Pin ${cell.key}`}
              aria-pressed={isPinned}
              onClick={() => onPin(key)}
            >
              📌
            </button>
            <span className="col-order-label">{cell.key}</span>
          </div>
        );
      })}
    </>
  );
}
