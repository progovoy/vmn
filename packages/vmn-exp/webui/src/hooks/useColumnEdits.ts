/** The leaderboard header's column edits: drag (saved order), resize, and
 *  the column menu's move/hide/pin (move keeps a pinned column among the
 *  pinned ones, in the URL's `col=`). */
import { useMemo } from "react";
import { isInnerRunId } from "../pages/innerRunColumns";
import { moveColumn, shiftColumn } from "../pages/leaderboardColumns";
import type { ColumnEdits } from "../pages/LeaderboardHead";
import type { useColumnPrefs } from "./useColumnPrefs";
import type { useLeaderboardColumns } from "./useLeaderboardColumns";
import type { useLeaderboardView } from "./useLeaderboardView";

export function useColumnEdits(
  view: ReturnType<typeof useLeaderboardView>,
  cols: ReturnType<typeof useLeaderboardColumns>,
  prefs: ReturnType<typeof useColumnPrefs>,
): ColumnEdits {
  const { setWidth, setOrder } = prefs;
  const ids = cols.layout.ids;
  const { defaultKeys, pinned, defaultPins } = cols;
  const { moveColumn: moveUrlColumn, toggleHidden, setColumnShown, togglePin } = view;
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
    onHide: (id) => (isInnerRunId(id) ? setColumnShown(id, false) : toggleHidden(id)),
    onPin: (id) => togglePin(id, pinned, defaultPins),
    pinned,
  }), [setWidth, setOrder, ids, defaultKeys, pinned, defaultPins, moveUrlColumn, toggleHidden, setColumnShown, togglePin]);
}
