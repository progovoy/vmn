import { useCallback, useEffect, useState } from "react";

/** "system" follows prefers-color-scheme; the others pin a palette. */
export type ThemePref = "system" | "light" | "dark";

export const THEME_KEY = "vmn_theme";
/** Fired on window whenever the applied theme may have changed. */
export const THEME_EVENT = "vmn-theme-change";

const CYCLE: ThemePref[] = ["system", "light", "dark"];

export const nextTheme = (pref: ThemePref): ThemePref =>
  CYCLE[(CYCLE.indexOf(pref) + 1) % CYCLE.length];

function storedTheme(): ThemePref {
  let v: string | null = null;
  try { v = localStorage.getItem(THEME_KEY); } catch { /* storage disabled */ }
  return CYCLE.includes(v as ThemePref) ? (v as ThemePref) : "system";
}

/** Pin the palette on <html> (none for "system") and tell the charts. */
export function applyTheme(pref: ThemePref) {
  const root = document.documentElement;
  if (pref === "system") delete root.dataset.theme;
  else root.dataset.theme = pref;
  window.dispatchEvent(new Event(THEME_EVENT));
}

/** The persisted theme preference and its setter. */
export function useTheme(): [ThemePref, (pref: ThemePref) => void] {
  const [pref, setPref] = useState(storedTheme);
  useEffect(() => applyTheme(pref), [pref]);
  const set = useCallback((next: ThemePref) => {
    try { localStorage.setItem(THEME_KEY, next); } catch { /* not persisted */ }
    setPref(next);
  }, []);
  return [pref, set];
}

/** A counter that moves whenever the palette does (a toggle or an OS
 *  switch) — list it as a memo dependency to re-read CSS colours. */
export function useThemeVersion(): number {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const bump = () => setVersion((v) => v + 1);
    window.addEventListener(THEME_EVENT, bump);
    const mq = typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-color-scheme: light)") : null;
    mq?.addEventListener?.("change", bump);
    return () => {
      window.removeEventListener(THEME_EVENT, bump);
      mq?.removeEventListener?.("change", bump);
    };
  }, []);
  return version;
}
