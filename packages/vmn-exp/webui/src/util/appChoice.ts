/** A choice remembered per workspace and app in localStorage (`<key>:<ws>/<app>`),
 *  e.g. the experiments page's view or an outer run's Runs tab layout. */
const storageKey = (key: string, ws: string, app: string) => `${key}:${ws}/${app}`;

/** The stored choice when *valid*, else null (also without localStorage). */
export function storedChoice<T extends string>(
  key: string, ws: string, app: string, valid: (v: string | null) => v is T,
): T | null {
  try {
    const v = localStorage.getItem(storageKey(key, ws, app));
    return valid(v) ? v : null;
  } catch {
    return null;
  }
}

export function rememberChoice(key: string, ws: string, app: string, value: string) {
  try { localStorage.setItem(storageKey(key, ws, app), value); } catch { /* not persisted */ }
}
