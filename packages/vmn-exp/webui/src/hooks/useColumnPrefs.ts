import { useCallback, useEffect, useState } from "react";

/** A board's own column arrangement: dragged widths and the column order. */
export interface ColumnPrefs {
  widths: Record<string, number>;
  order: readonly string[];
}

export const EMPTY_PREFS: ColumnPrefs = { widths: {}, order: [] };
const keyOf = (scope: string) => `vmn_columns:${scope}`;

function load(scope: string): ColumnPrefs {
  try {
    const v = JSON.parse(localStorage.getItem(keyOf(scope)) ?? "null");
    if (!v || typeof v !== "object") return EMPTY_PREFS;
    return {
      widths: v.widths && typeof v.widths === "object" ? v.widths : {},
      order: Array.isArray(v.order) ? v.order.filter((c: unknown) => typeof c === "string") : [],
    };
  } catch {
    return EMPTY_PREFS;
  }
}

function save(scope: string, prefs: ColumnPrefs) {
  try {
    if (prefs === EMPTY_PREFS) localStorage.removeItem(keyOf(scope));
    else localStorage.setItem(keyOf(scope), JSON.stringify(prefs));
  } catch { /* not persisted */ }
}

/** Column widths and order for *scope* (one per app), kept in the browser
 *  rather than the URL: it's a layout preference, not part of a shared view. */
export function useColumnPrefs(scope: string) {
  const [prefs, setPrefs] = useState(() => load(scope));
  useEffect(() => { save(scope, prefs); }, [scope, prefs]);
  const setWidth = useCallback(
    (id: string, width: number) => setPrefs((p) => ({ ...p, widths: { ...p.widths, [id]: width } })),
    [],
  );
  const setOrder = useCallback(
    (order: readonly string[]) => setPrefs((p) => ({ ...p, order })),
    [],
  );
  const reset = useCallback(() => setPrefs(EMPTY_PREFS), []);
  const customized = Object.keys(prefs.widths).length > 0 || prefs.order.length > 0;
  return { ...prefs, setWidth, setOrder, reset, customized };
}
