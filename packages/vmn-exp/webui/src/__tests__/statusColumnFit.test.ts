/// <reference types="vite/client" />
/** The leaderboard's status column fits its widest pill, read from the
 *  stylesheet: jsdom lays nothing out, so the guard does the arithmetic. */
import { describe, it, expect } from "vitest";
import styles from "../styles.css?raw";
import { defaultWidth } from "../pages/leaderboardColumns";

/** Every declaration of the rules whose selector list names *selector*. */
function decls(css: string, selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  const plain = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const [, head, body] of plain.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
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

function horizontalPadding(d: Record<string, string>): [number, number] {
  const parts = (d.padding ?? "").split(/\s+/).filter(Boolean);
  const right = parts.length > 1 ? parts[1] : parts[0];
  const left = parts.length > 3 ? parts[3] : right;
  return [px(d["padding-left"] ?? left), px(d["padding-right"] ?? right)];
}

/** A monospace glyph's advance, in em (IBM Plex Mono, Menlo, SF Mono). */
const MONO_ADVANCE_EM = 0.6;
const WIDEST = "succeeded";

describe("the leaderboard's status column", () => {
  it("fits the widest status pill, so no pill is cut off with an ellipsis", () => {
    const pill = decls(styles, ".status-pill");
    const dot = decls(styles, ".status-pill .dot");
    const [pillLeft, pillRight] = horizontalPadding(pill);
    const pillWidth = WIDEST.length * MONO_ADVANCE_EM * px(pill["font-size"])
      + px(dot.width) + px(pill.gap) + pillLeft + pillRight + 2;  // + the 1px border each side
    const [left, right] = horizontalPadding({ ...decls(styles, "td"), ...decls(styles, "td.status-cell") });
    expect(defaultWidth("status") - left - right).toBeGreaterThanOrEqual(pillWidth);
  });

  it("aligns its header with the pills", () => {
    const cell = horizontalPadding({ ...decls(styles, "td"), ...decls(styles, "td.status-cell") });
    const head = horizontalPadding({ ...decls(styles, "th"), ...decls(styles, "th.status-col-head") });
    expect(head).toEqual(cell);
  });
});
