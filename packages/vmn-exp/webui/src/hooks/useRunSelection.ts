import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import {
  parsePicks, rawPicks, readPicks, subscribePicks, writePicks, type RunPick,
} from "../util/runSelection";
import {
  parseGroups, rawGroups, readGroups, removeQueryGroup, selectExactly, selectedVerstrs, writeGroups,
  type QueryGroup,
} from "../util/selectionGroups";

/** What a board knows of a verstr it selects (its row), if anything. */
export type PickMeta = (verstr: string) => RunPick | undefined;

/** The app's run selection (the tray's picks and query groups), shared by
 *  every board and page of (*ws*, *app*) and kept in sessionStorage. Every
 *  write reads the stored selection first, so several in one tick compose. */
export function useRunSelection(ws: string, app: string) {
  const raw = useSyncExternalStore(subscribePicks, () => rawPicks(ws, app));
  const rawG = useSyncExternalStore(subscribePicks, () => rawGroups(ws, app));
  const picks = useMemo(() => parsePicks(raw), [raw]);
  const groups = useMemo(() => parseGroups(rawG), [rawG]);
  const selected: ReadonlySet<string> = useMemo(() => new Set(selectedVerstrs(picks, groups)), [picks, groups]);

  /** Select exactly *verstrs*, keeping what was known of each pick. */
  const setSelected = useCallback(
    (verstrs: readonly string[], metaOf?: PickMeta) => selectExactly(ws, app, verstrs, metaOf),
    [ws, app],
  );
  /** Unticking a group's member turns the group back into picks of the rest. */
  const toggleSelected = useCallback((verstr: string, meta?: RunPick) => {
    const cur = selectedVerstrs(readPicks(ws, app), readGroups(ws, app));
    if (cur.includes(verstr)) selectExactly(ws, app, cur.filter((v) => v !== verstr));
    else writePicks(ws, app, [...readPicks(ws, app), meta ?? { verstr }]);
  }, [ws, app]);
  const remove = useCallback(
    (verstr: string) => writePicks(ws, app, readPicks(ws, app).filter((p) => p.verstr !== verstr)),
    [ws, app],
  );
  const removeGroup = useCallback((group: QueryGroup) => removeQueryGroup(ws, app, group), [ws, app]);
  const clear = useCallback(() => {
    writeGroups(ws, app, [], false);
    writePicks(ws, app, []);
  }, [ws, app]);

  return { picks, groups, selected, setSelected, toggleSelected, remove, removeGroup, clear };
}

/** A URL `sel` (a shared link) replaces the app's selection before it is
 *  read, and then leaves the URL: the store is the selection from then on. */
export function useSeedSelection(ws: string, app: string, sel: readonly string[], dropSel: () => void) {
  // Silent while rendering; the effect tells the components already drawn.
  if (sel.length) {
    writeGroups(ws, app, [], false);
    writePicks(ws, app, sel.map((verstr) => ({ verstr })), false);
  }
  const hasSel = sel.length > 0;
  useEffect(() => {
    if (!hasSel) return;
    writePicks(ws, app, readPicks(ws, app));
    dropSel();
  }, [ws, app, hasSel, dropSel]);
}
