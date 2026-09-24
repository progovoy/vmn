/** Canvas can't paint `var(--x)`: resolve design tokens to real colours. */

export function readCssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name);
}

const VAR_RE = /^var\((--[\w-]+)\)$/;

/** Follows `var(--x)` chains through *read*; plain colours pass through. */
export function resolveCssColor(
  color: string, read: (name: string) => string = readCssVar, fallback = color,
): string {
  let c = color.trim();
  for (let hops = 0; hops < 8; hops++) {
    const m = VAR_RE.exec(c);
    if (!m) return c;
    c = read(m[1]).trim();
    if (!c) return fallback;
  }
  return fallback;
}
