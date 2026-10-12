/// <reference types="vite/client" />
/** The app's one checkbox look, read from the stylesheets themselves: jsdom
 *  lays nothing out, so the clipping and contrast guards do the arithmetic. */
import { describe, it, expect } from "vitest";
import styles from "../styles.css?raw";
import look from "../styles/checkbox.css?raw";
import { defaultWidth } from "../pages/leaderboardColumns";

const BOX_PX = 16;
/** The focus ring (2px outline, 2px offset) on each side. */
const RING_PX = 4;

/** Every declaration of the rules whose selector list names *selector*. */
function decls(css: string, selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  const plain = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const [, head, body] of plain.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    // A rule's selector starts after any statement (`@import …;`) before it.
    const sel = head.slice(head.lastIndexOf(";") + 1);
    if (!sel.split(",").map((s) => s.trim()).includes(selector)) continue;
    for (const d of body.split(";")) {
      const at = d.indexOf(":");
      if (at > 0) out[d.slice(0, at).trim()] = d.slice(at + 1).trim();
    }
  }
  return out;
}

const px = (v: string | undefined) => (v ? parseFloat(v) || 0 : 0);

/** Left and right padding (px) of a rule, from the shorthand or the longhands. */
function horizontalPadding(d: Record<string, string>): [number, number] {
  const parts = (d.padding ?? "").split(/\s+/).filter(Boolean);
  const right = parts.length > 1 ? parts[1] : parts[0];
  const left = parts.length > 3 ? parts[3] : right;
  return [px(d["padding-left"] ?? left), px(d["padding-right"] ?? right)];
}

/** *value* with its var() chain resolved: the theme's block first, then :root. */
function resolve(value: string, theme: Record<string, string>, root: Record<string, string>): string {
  const ref = /^var\((--[\w-]+)\)$/.exec(value.trim());
  if (!ref) return value.trim();
  return resolve(theme[ref[1]] ?? root[ref[1]] ?? "", theme, root);
}

function luminance(hex: string): number {
  const ch = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const BOX = 'input[type="checkbox"]';

describe("the checkbox look", () => {
  it("draws a 16px rounded box with a 1.5px border instead of the native control", () => {
    const d = decls(look, BOX);
    expect(d.appearance).toBe("none");
    expect(d.width).toBe(`${BOX_PX}px`);
    expect(d.height).toBe(`${BOX_PX}px`);
    expect(d["border-radius"]).toBe("4px");
    expect(d.border).toMatch(/^1\.5px solid var\(--[\w-]+\)$/);
  });

  it("fills checked and indeterminate boxes with the accent and a white mark", () => {
    for (const state of [":checked", ":indeterminate"]) {
      const d = decls(look, `${BOX}${state}`);
      expect(d["background-color"]).toBe("var(--accent)");
      expect(d["border-color"]).toBe("var(--accent)");
      expect(d["background-image"]).toMatch(/^url\("data:image\/svg\+xml,.*%23fff/);
    }
    expect(decls(look, `${BOX}:checked`)["background-image"])
      .not.toBe(decls(look, `${BOX}:indeterminate`)["background-image"]);
  });

  it("shows an accent border on hover and a ring on keyboard focus", () => {
    expect(decls(look, `${BOX}:hover`)["border-color"]).toBe("var(--accent)");
    expect(decls(look, `${BOX}:focus-visible`).outline).toMatch(/^2px solid/);
  });

  it("is the one checkbox rule, shared by the app and exported reports", () => {
    expect(styles).toMatch(/^@import "\.\/styles\/checkbox\.css";/m);
    expect(Object.keys(decls(styles, BOX))).toEqual([]);
  });

  it("keeps the box's border clearly visible on the panels in both themes", () => {
    const root = decls(styles, ":root");
    const light = decls(styles, ':root[data-theme="light"]');
    const border = /var\(--[\w-]+\)/.exec(decls(look, BOX).border)![0];
    for (const theme of [{}, light]) {
      for (const surface of ["var(--panel)", "var(--panel-2)"]) {
        const ratio = contrast(resolve(border, theme, root), resolve(surface, theme, root));
        expect(ratio).toBeGreaterThanOrEqual(3);
      }
    }
  });
});

describe("the leaderboard's check column", () => {
  it("fits the box and its focus ring, centred, so nothing is clipped", () => {
    const cell = decls(styles, "td.check-cell");
    const [left, right] = horizontalPadding({ ...decls(styles, "td"), ...cell });
    expect(defaultWidth("check") - left - right).toBeGreaterThanOrEqual(BOX_PX + 2 * RING_PX);
    expect(cell["text-align"]).toBe("center");
    expect(decls(styles, "th.check-cell")["text-align"]).toBe("center");
  });
});
