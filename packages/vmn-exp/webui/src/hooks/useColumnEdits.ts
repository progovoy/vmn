/** The leaderboard header's column edits: drag (saved order), resize, and
 *  the column menu's move/hide/pin (move keeps a pinned column among the
 *  pinned ones, in the URL's `col=`). */
import { useMemo } from "react";
import { moveColumn, shiftColumn } from "../pages/leaderboardColumns";
import type { ColumnEdits } from "../pages/LeaderboardHead";
import type { useColumnPrefs } from "./useColumnPrefs";
import { COMMENTS_COLUMN, type useLeaderboardColumns } from "./useLeaderboardColumns";
import type { useLeaderboardView } from "./useLeaderboardView";

type View = ReturnType<typeof useLeaderboardView>;

/** Turn column *id* off: comments flip their `hide=` key, a schema-hidden
 *  metric drops its keys (`hide=` would show it), the rest write `hide=`. */
export function hideColumn(
  view: Pick<View, "toggleHidden" | "resetColumn" | "setColumnShown">,
  schemaHidden: readonly string[],
  id: string,
) {
  if (id === COMMENTS_COLUMN) view.toggleHidden(id);
  else if (id.startsWith("m:") && schemaHidden.includes(id.slice(2))) view.resetColumn(id);
  else view.setColumnShown(id, false);
}

export function useColumnEdits(
  view: View,
  cols: ReturnType<typeof useLeaderboardColumns>,
  prefs: ReturnType<typeof useColumnPrefs>,
): ColumnEdits {
  const { setWidth, setOrder } = prefs;
  const ids = cols.layout.ids;
  const { defaultKeys, pinned, defaultPins, schemaHidden } = cols;
  const { moveColumn: moveUrlColumn, togglePin, toggleHidden, resetColumn, setColumnShown } = view;
  return useMemo<ColumnEdits>(() => ({
    onResize: setWidth,
    onMove: (from, to) => {
      const next = moveColumn(ids ?? [], from, to);
      if (next !== ids) setOrder(next);
    },
    onShift: (id, delta) => {
      if (pinned.includes(id)) return moveUrlColumn(id, delta, defaultKeys, pinned);
      const next = shiftColumn(ids ?? [], id, delta, new Set(pinned));
      if (next !== ids) setOrder(next);
    },
    onHide: (id) => hideColumn({ toggleHidden, resetColumn, setColumnShown }, schemaHidden, id),
    onPin: (id) => togglePin(id, pinned, defaultPins),
    pinned,
  }), [
    setWidth, setOrder, ids, defaultKeys, pinned, defaultPins, schemaHidden,
    moveUrlColumn, togglePin, toggleHidden, resetColumn, setColumnShown,
  ]);
}
