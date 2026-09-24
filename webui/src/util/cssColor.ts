/** Canvas can't paint `var(--x)`: resolve design-system variables to the
 *  concrete colours the current theme defines. */

const FALLBACK = "#888888";
const VAR_RE = /^var\(\s*(--[\w-]+)\s*(?:,\s*(.+))?\)$/;

export function readCssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name);
}

/** Follows `var(--x)` chains through *read*; plain colours pass through. An
 *  undefined variable falls back to the var()'s own fallback, then *fallback*. */
export function resolveCssColor(
  color: string, read: (name: string) => string = readCssVar, fallback = FALLBACK,
): string {
  const m = VAR_RE.exec(color.trim());
  if (!m) return color.trim();
  const value = read(m[1]).trim();
  if (value) return resolveCssColor(value, read, fallback);
  return m[2] ? resolveCssColor(m[2], read, fallback) : fallback;
}

export interface ChartTheme {
  axis: string;
  grid: string;
  text: string;
}

export function chartTheme(read: (name: string) => string = readCssVar): ChartTheme {
  return {
    axis: resolveCssColor("var(--text-3)", read),
    grid: resolveCssColor("var(--line)", read),
    text: resolveCssColor("var(--text-2)", read),
  };
}
