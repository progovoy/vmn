/** WCAG contrast arithmetic for the stylesheet tests (jsdom draws nothing,
 *  so the tests read the colours from the CSS and compute). */

/** `#rrggbb` as `[r, g, b]`. */
export const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

export function luminance([r, g, b]: number[]): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

export function contrast(a: number[], b: number[]): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** *fg* at *pct* over *bg*, as color-mix(in srgb) draws it. */
export const mix = (fg: number[], bg: number[], pct: number) => fg.map((c, i) => c * pct + bg[i] * (1 - pct));
