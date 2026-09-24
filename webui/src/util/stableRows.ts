/** Structural equality over the JSON values the API returns. */
export function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) {
    return Number.isNaN(a) && Number.isNaN(b);
  }
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a)) {
    const bb = b as unknown[];
    return a.length === bb.length && a.every((v, i) => sameValue(v, bb[i]));
  }
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  const ob = b as Record<string, unknown>;
  return ka.every((k) => k in ob && sameValue((a as Record<string, unknown>)[k], ob[k]));
}

type Keyed = { verstr: string };

/** *next* with every row that did not change swapped for the previous object
 *  (matched by verstr), so memoized rows and charts skip unchanged runs — and
 *  the previous array itself when nothing changed at all. */
export function stabilizeRows<T extends Keyed>(prev: readonly T[] | undefined | null, next: T[]): T[] {
  if (!prev || prev.length === 0) return next;
  const byVerstr = new Map(prev.map((r) => [r.verstr, r]));
  let allSame = prev.length === next.length;
  for (let i = 0; i < next.length; i++) {
    const old = byVerstr.get(next[i].verstr);
    if (old && sameValue(old, next[i])) next[i] = old;
    if (next[i] !== prev[i]) allSame = false;
  }
  return allSame ? (prev as T[]) : next;
}

/** The previous rows when a poll brought the same data, else the new array
 *  (with its unchanged rows keeping their previous identity). */
export function keepIfUnchanged<T>(prev: T[] | null, next: T[]): T[] {
  if (!prev || prev.length !== next.length) return next;
  return sameValue(prev, next) ? prev : next;
}
