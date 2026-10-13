/// <reference types="vite/client" />
/** Plan 22 F9, read from the stylesheets (jsdom lays nothing out): the
 *  selected aggregate reads at 4.5:1 in both themes, and on a phone the
 *  Group by menu opens under its trigger, whatever the page's scroll. */
import { describe, it, expect } from "vitest";
import menuCss from "../GroupByMenu.css?raw";
import styles from "../../styles.css?raw";
import { contrast, mix, rgb } from "../../__tests__/contrastHelpers";

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
  const m = value.match(/^color-mix\(in srgb,\s*var\((--[\w-]+)\)\s+([\d.]+)%,\s*(transparent|var\((--[\w-]+)\))\)$/);
  expect(m, `a colour the test can resolve: ${value}`).not.toBeNull();
  const fg = token(m![1], theme);
  const bg = m![4] ? token(m![4], theme) : under;
  return mix(fg, bg, Number(m![2]) / 100);
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

describe("the keyboard focus on the selected aggregate (plan 22 F10)", () => {
  /** The 2px ring the focused choice draws: an inset box-shadow (drawn on
   *  the choice's tint) or an outline (drawn on the menu). */
  function ring(d: Record<string, string>): { colour: string; inset: boolean } | null {
    const shadow = d["box-shadow"]?.match(/^inset 0 0 0 2px (.+)$/);
    if (shadow) return { colour: shadow[1], inset: true };
    const outline = d.outline?.match(/^2px solid (.+)$/);
    return outline ? { colour: outline[1], inset: false } : null;
  }

  for (const theme of ["dark", "light"] as const) {
    it(`draws a 2px ring at 3:1 against what it sits on in the ${theme} theme`, () => {
      const focused = decls(menuCss, `${SELECTED}:focus-visible`);
      const r = ring(focused);
      expect(r, "a 2px focus ring on the selected aggregate").not.toBeNull();
      const menuBg = token("--panel-2", theme);
      const bg = { ...decls(menuCss, SELECTED), ...focused }.background;
      const under = r!.inset && bg ? resolve(bg, theme, menuBg) : menuBg;
      expect(contrast(resolve(r!.colour, theme, under), under)).toBeGreaterThanOrEqual(3);
    });
  }
});

describe("the phone Group by menu (plan 22 F9)", () => {
  it("opens under its trigger at any scroll: fixed at the trigger's bottom, inside the viewport", () => {
    const d = decls(media(menuCss, "(max-width: 639px)"), ".group-by-menu");
    expect(d.position).toBe("fixed");
    // GroupByMenu sets --group-by-top to its trigger's bottom (a fixed box's
    // static top ignores the scroll of the page's own scroller).
    expect(d.top).toBe("var(--group-by-top, auto)");
    expect(d.left).toBe("12px");
    expect(d.right).toBe("12px");
    expect(d["min-width"]).toBe("0");
  });
});
