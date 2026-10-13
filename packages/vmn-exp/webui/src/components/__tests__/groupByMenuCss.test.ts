/// <reference types="vite/client" />
/** Plan 22 F9, read from the stylesheets (jsdom lays nothing out): the
 *  selected aggregate reads at 4.5:1 in both themes, and on a phone the
 *  Group by menu opens under its trigger, whatever the page's scroll. */
import { describe, it, expect } from "vitest";
import menuCss from "../GroupByMenu.css?raw";
import styles from "../../styles.css?raw";

const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");

function media(css: string, query: string): string {
  const plain = strip(css);
  const at = plain.indexOf(`@media ${query}`);
  expect(at, `@media ${query}`).toBeGreaterThanOrEqual(0);
  let depth = 0;
  const open = plain.indexOf("{", at);
  for (let i = open; i < plain.length; i++) {
    if (plain[i] === "{") depth++;
    else if (plain[i] === "}" && --depth === 0) return plain.slice(open + 1, i);
  }
  throw new Error(`unbalanced @media ${query}`);
}

/** The declarations every rule naming *selector* sets, later ones winning. */
function decls(css: string, selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [, head, body] of strip(css).matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (!head.split(",").map((s) => s.trim()).includes(selector)) continue;
    for (const d of body.split(";")) {
      const i = d.indexOf(":");
      if (i > 0) out[d.slice(0, i).trim()] = d.slice(i + 1).trim();
    }
  }
  return out;
}

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const lum = (c: number[]) => {
  const lin = (v: number) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
};
const contrast = (a: number[], b: number[]) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

/** A theme's colour token: dark is `:root`'s `--x`, light its `--light-x`. */
function token(name: string, theme: "dark" | "light"): number[] {
  const key = theme === "light" ? `--light-${name.slice(2)}` : name;
  const m = strip(styles).match(new RegExp(`${key}:\\s*(#[0-9a-fA-F]{6})`));
  expect(m, key).not.toBeNull();
  return rgb(m![1]);
}

/** A declared colour over *under*: `#fff`, `var(--x)` or
 *  `color-mix(in srgb, var(--x) N%, transparent|var(--y))`. */
function resolve(value: string, theme: "dark" | "light", under: number[]): number[] {
  if (/^#fff(fff)?$/i.test(value)) return [255, 255, 255];
  const plain = value.match(/^var\((--[\w-]+)\)$/);
  if (plain) return token(plain[1], theme);
  const mix = value.match(/^color-mix\(in srgb,\s*var\((--[\w-]+)\)\s+([\d.]+)%,\s*(transparent|var\((--[\w-]+)\))\)$/);
  expect(mix, `a colour the test can resolve: ${value}`).not.toBeNull();
  const fg = token(mix![1], theme);
  const bg = mix![4] ? token(mix![4], theme) : under;
  const p = Number(mix![2]) / 100;
  return fg.map((c, i) => c * p + bg[i] * (1 - p));
}

const SELECTED = '.group-by-section[aria-label="Aggregate"] .group-by-item[aria-checked="true"]';

describe("the Group by menu's selected aggregate (plan 22 F9)", () => {
  for (const theme of ["dark", "light"] as const) {
    it(`reads at 4.5:1 on its own background in the ${theme} theme`, () => {
      const d = decls(menuCss, SELECTED);
      const menuBg = token("--panel-2", theme);
      const bg = d.background ? resolve(d.background, theme, menuBg) : menuBg;
      expect(d.color, "the selected aggregate sets its text colour").toBeDefined();
      expect(contrast(resolve(d.color, theme, bg), bg)).toBeGreaterThanOrEqual(4.5);
    });
  }

  it("outlines the choice in the accent, so it does not rest on a tint alone", () => {
    expect(decls(menuCss, SELECTED)["box-shadow"]).toMatch(/inset .*var\(--accent\)/);
  });
});

describe("the phone Group by menu (plan 22 F9)", () => {
  it("opens under its trigger at any scroll: fixed at its static top, inside the viewport", () => {
    const d = decls(media(menuCss, "(max-width: 639px)"), ".group-by-menu");
    expect(d.position).toBe("fixed");
    expect(d.top).toBe("auto");
    expect(d.left).toBe("12px");
    expect(d.right).toBe("12px");
    expect(d["min-width"]).toBe("0");
  });
});
