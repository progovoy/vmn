/** fnmatch globs over metric names, matched like the server's
 *  `define_metric` patterns: `*`, `?` and `[...]` (`[!...]` negates), all
 *  else literal, case-sensitive. */

const globCache = new Map<string, RegExp>();

export function globRegExp(pattern: string): RegExp {
  let re = globCache.get(pattern);
  if (re) return re;
  let src = "";
  for (let i = 0; i < pattern.length; i++) {
    const c = pattern[i];
    const close = c === "[" ? pattern.indexOf("]", i + 2) : -1;
    if (c === "*") src += ".*";
    else if (c === "?") src += ".";
    else if (close > 0) {
      const body = pattern.slice(i + 1, close).replace(/\\/g, "\\\\");
      src += body.startsWith("!") ? `[^${body.slice(1)}]` : `[${body}]`;
      i = close;
    } else src += c.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  re = new RegExp(`^${src}$`, "s");
  globCache.set(pattern, re);
  return re;
}

export const isGlob = (key: string) => /[*?[]/.test(key);

/** The *names* *pattern* matches, sorted. */
export function matchKeys(pattern: string, names: Iterable<string>): string[] {
  const re = globRegExp(pattern);
  return [...names].filter((n) => re.test(n)).sort();
}

/** *keys* with each glob replaced by the *names* it matches (a key naming a
 *  metric exactly stays itself), in order, without repeats. */
export function expandKeys(keys: string[], names: Iterable<string>): string[] {
  const known = new Set(names);
  const out = new Set<string>();
  for (const key of keys) {
    const matched = isGlob(key) && !known.has(key) ? matchKeys(key, known) : [key];
    for (const m of matched) out.add(m);
  }
  return [...out];
}
