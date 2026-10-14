import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import {
  parsePicks, rawPicks, readPicks, subscribePicks, writePicks, type RunPick,
} from "../util/runSelection";

/** What a board knows of a verstr it selects (its row), if anything. */
export type PickMeta = (verstr: string) => RunPick | undefined;

/** The app's run selection (the tray's picks), shared by every board and
 *  page of (*ws*, *app*) and kept in sessionStorage. Every write reads the
 *  stored picks first, so several in one tick compose. */
export function useRunSelection(ws: string, app: string) {
  const raw = useSyncExternalStore(subscribePicks, () => rawPicks(ws, app));
  const picks = useMemo(() => parsePicks(raw), [raw]);
  const selected: ReadonlySet<string> = useMemo(() => new Set(picks.map((p) => p.verstr)), [picks]);

  /** Select exactly *verstrs*, keeping what was known of each pick. */
  const setSelected = useCallback((verstrs: readonly string[], metaOf?: PickMeta) => {
    const known = new Map(readPicks(ws, app).map((p) => [p.verstr, p]));
    writePicks(ws, app, verstrs.map((v) => metaOf?.(v) ?? known.get(v) ?? { verstr: v }));
  }, [ws, app]);
  const toggleSelected = useCallback((verstr: string, meta?: RunPick) => {
    const cur = readPicks(ws, app);
    writePicks(ws, app, cur.some((p) => p.verstr === verstr)
      ? cur.filter((p) => p.verstr !== verstr)
      : [...cur, meta ?? { verstr }]);
  }, [ws, app]);
  const remove = useCallback(
    (verstr: string) => writePicks(ws, app, readPicks(ws, app).filter((p) => p.verstr !== verstr)),
    [ws, app],
  );
  const clear = useCallback(() => writePicks(ws, app, []), [ws, app]);

  return { picks, selected, setSelected, toggleSelected, remove, clear };
}

/** A URL `sel` (a shared link) replaces the app's selection before it is
 *  read, and then leaves the URL: the store is the selection from then on. */
export function useSeedSelection(ws: string, app: string, sel: readonly string[], dropSel: () => void) {
  // Silent while rendering; the effect tells the components already drawn.
  if (sel.length) writePicks(ws, app, sel.map((verstr) => ({ verstr })), false);
  const hasSel = sel.length > 0;
  useEffect(() => {
    if (!hasSel) return;
    writePicks(ws, app, readPicks(ws, app));
    dropSel();
  }, [ws, app, hasSel, dropSel]);
}
