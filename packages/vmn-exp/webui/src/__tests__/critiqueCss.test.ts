/** Contrast and glyph floors from the plan-19 critique (plan 20 E6). Vitest
 *  stubs imported CSS, so the files are read from disk (run from webui/). */
import { describe, it, expect, beforeAll } from "vitest";

type Fs = { readFileSync(path: string, encoding: "utf8"): string };
let styles = "";
let crumbs = "";
let forms = "";
let icons = "";
beforeAll(async () => {
  const fs: Fs = await import(/* @vite-ignore */ "node:fs" as string);
  styles = fs.readFileSync("src/styles.css", "utf8");
  crumbs = fs.readFileSync("src/components/shell/Crumbs.css", "utf8");
  forms = fs.readFileSync("src/styles/forms.css", "utf8");
  icons = fs.readFileSync("src/components/shell/icons.tsx", "utf8");
});

function token(name: string): string {
  const m = styles.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`));
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
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(rgb(a)), luminance(rgb(b))].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
const block = (css: string, selector: string) => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const m = css.match(new RegExp(`(^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`, "m"));
  expect(m, selector).not.toBeNull();
  return m![2];
};

describe("muted text (created pill, placeholders) reads at AA on both themes", () => {
  it.each([
    ["--text-3", ["--panel-2", "--panel", "--bg"]],
    ["--light-text-3", ["--light-panel-2", "--light-panel", "--light-bg"]],
  ])("%s on its surfaces", (fg, surfaces) => {
    for (const bg of surfaces) expect(contrast(token(fg), token(bg)), bg).toBeGreaterThanOrEqual(4.5);
  });

  it("colours placeholders with --text-3 at full opacity, imported by styles.css", () => {
    const rule = block(forms, "::placeholder");
    expect(rule).toMatch(/color:\s*var\(--text-3\)/);
    expect(rule).toMatch(/opacity:\s*1/);
    expect(styles).toMatch(/@import "\.\/styles\/forms\.css";/);
  });
});

describe("chrome", () => {
  it("draws the copy-as-CLI icon in --text-2 (3:1 or more)", () => {
    expect(block(crumbs, ".crumb-copy")).toMatch(/color:\s*var\(--text-2\)/);
    expect(contrast(token("--text-2"), token("--panel"))).toBeGreaterThanOrEqual(3);
    expect(contrast(token("--light-text-2"), token("--light-panel"))).toBeGreaterThanOrEqual(3);
  });

  it("separates the sidebar from the content with its own border token, stronger than --line in dark", () => {
    expect(block(styles, ".sidebar")).toMatch(/border-right:\s*1px solid var\(--sidebar-line\)/);
    expect(styles).toMatch(/--sidebar-line:\s*var\(--line-2\)/);
    expect(contrast(token("--line-2"), token("--bg"))).toBeGreaterThan(contrast(token("--line"), token("--bg")));
  });

  it("draws .select-wrap's chevron from the shell's chevron-down icon, not a ▾ glyph", () => {
    const after = block(styles, ".select-wrap::after");
    expect(after).not.toMatch(/▾/);
    const chevron = icons.match(/"chevron-down":\s*\["([^"]+)"\]/)![1];
    expect(after).toContain(chevron);
    expect(after).toMatch(/mask:/);
    expect(after).toMatch(/background:\s*var\(--text-2\)/);
  });
});
