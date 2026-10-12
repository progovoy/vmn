/** styles.css floors (plan 19 §1.11): AA light-mode status pills, reduced
 *  motion, readable copy-path text. */
import { describe, it, expect, beforeAll } from "vitest";

// Vitest stubs imported CSS, so read it from disk (vitest runs from webui/).
type Fs = { readFileSync(path: string, encoding: "utf8"): string };
let css = "";
beforeAll(async () => {
  const fs: Fs = await import(/* @vite-ignore */ "node:fs" as string);
  css = fs.readFileSync("src/styles.css", "utf8");
});

function token(name: string): string {
  const m = css.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`));
  expect(m, name).not.toBeNull();
  return m![1];
}

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

function luminance([r, g, b]: number[]): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function contrast(a: number[], b: number[]): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** *fg* at *pct* over *bg*, as color-mix(in srgb) draws it. */
const mix = (fg: number[], bg: number[], pct: number) => fg.map((c, i) => c * pct + bg[i] * (1 - pct));

const WHITE = [255, 255, 255];

describe("light-mode status pills", () => {
  for (const name of ["--light-st-good", "--light-st-bad", "--light-st-stuck"]) {
    it(`${name} reads at 4.5:1 on panel-2 and on white`, () => {
      const fg = rgb(token(name));
      expect(contrast(fg, rgb(token("--light-panel-2")))).toBeGreaterThanOrEqual(4.5);
      expect(contrast(fg, WHITE)).toBeGreaterThanOrEqual(4.5);
    });
  }

  it("keeps stuck at 4.5:1 on its own 12% tint over panel-2", () => {
    const fg = rgb(token("--light-st-stuck"));
    const tint = mix(fg, rgb(token("--light-panel-2")), 0.12);
    expect(contrast(fg, tint)).toBeGreaterThanOrEqual(4.5);
  });

  it("colours the pills from the pill tokens", () => {
    expect(css).toMatch(/\.status-pill\.succeeded\s*\{[^}]*color:\s*var\(--st-good\)/);
    expect(css).toMatch(/\.status-pill\.failed\s*\{[^}]*color:\s*var\(--st-bad\)/);
    expect(css).toMatch(/\.status-pill\.stuck\s*\{[^}]*color:\s*var\(--st-stuck\)/);
    expect(css).toMatch(/\.status-pill\.running\s*\{[^}]*color:\s*var\(--st-running\)/);
  });
});

describe("motion and type floors", () => {
  it("stops animation under prefers-reduced-motion: reduce", () => {
    const block = css.match(/@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?)\}\s*\}/);
    expect(block).not.toBeNull();
    expect(block![1]).toMatch(/animation-duration:\s*\.01ms\s*!important/);
    expect(block![1]).toMatch(/transition-duration:\s*\.01ms\s*!important/);
  });

  it("sets copy-path text at 12px or more", () => {
    const size = css.match(/\.copy-path \.mono\s*\{[^}]*font-size:\s*([\d.]+)px/);
    expect(size).not.toBeNull();
    expect(Number(size![1])).toBeGreaterThanOrEqual(12);
  });
});
