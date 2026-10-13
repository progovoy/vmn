/// <reference types="vite/client" />
/** Plan 20 C8, read from the stylesheets (jsdom lays nothing out): at 390px
 *  nothing pushes the page sideways, the toolbar's popovers stay on screen,
 *  the palette's CLI column is not cut, and touch gets no key hints. */
import { describe, it, expect } from "vitest";
import toolbar from "../pages/leaderboardToolbar.css?raw";
import cards from "../pages/leaderboardCards.css?raw";
import palette from "../components/palette/palette.css?raw";
import topbar from "../components/shell/Topbar.css?raw";

const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");

/** The body of the first `@media <query>` block (balanced braces). */
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

/** Declarations of the rule whose selector list names *selector*, in *css*. */
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

const NARROW = "(max-width: 639px)";
const PHONE = "(max-width: 599px)";
const TOUCH = "(hover: none) and (pointer: coarse)";

describe("the 390px board", () => {
  it("pins the toolbar's popovers (Views, Columns) inside the viewport", () => {
    const pop = decls(media(toolbar, NARROW), ".toolbar .col-picker");
    expect(pop.position).toBe("fixed");
    expect(pop.left).toBe("12px");
    expect(pop.right).toBe("12px");
    expect(pop["min-width"]).toBe("0");
  });

  it("lets a card's long names and verstrs truncate instead of widening the page", () => {
    for (const sel of [".lb-mcard-name", ".lb-mcard-sub", ".lb-mcard-foot"]) {
      const d = decls(cards, sel);
      expect(d.overflow, sel).toBe("hidden");
      expect(d["text-overflow"], sel).toBe("ellipsis");
      expect(d["white-space"], sel).toBe("nowrap");
    }
    expect(decls(cards, ".lb-mcard-body")["min-width"]).toBe("0");
  });
});

describe("mobile chrome", () => {
  it("gives the palette's CLI equivalent its own full-width line on a phone", () => {
    const cli = decls(media(palette, PHONE), ".cmdk-row::after");
    expect(cli["grid-column"]).toBe("2 / -1");
    expect(cli["max-width"]).toBe("none");
  });

  it("drops the palette's keyboard legend on touch screens", () => {
    expect(decls(media(palette, TOUCH), ".cmdk-foot").display).toBe("none");
  });

  it("hides the identity text behind an initial only for a signed-in name", () => {
    const phone = media(topbar, PHONE);
    expect(decls(phone, ".id-chip.has-initial .id-text").position).toBe("absolute");
    expect(decls(phone, ".id-text").position).toBeUndefined();
  });
});
