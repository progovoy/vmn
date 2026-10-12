import { describe, it, expect, beforeAll } from "vitest";

// Vitest stubs imported CSS (even `?raw`), so read the file from disk; vitest
// runs from webui/. The specifier is a string so tsc needs no Node types.
type Fs = { readFileSync(path: string, encoding: "utf8"): string };
let css = "";
beforeAll(async () => {
  const fs: Fs = await import(/* @vite-ignore */ "node:fs" as string);
  css = fs.readFileSync("src/components/shell/Sidebar.css", "utf8");
});

/** The declarations of the first rule whose selector list is exactly *selector*. */
function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`(^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`, "m"));
  expect(match, `rule ${selector}`).not.toBeNull();
  return match![2];
}

describe("Sidebar.css", () => {
  it("sets nav labels at 11px or more", () => {
    const size = rule(".nav-label").match(/font-size:\s*([\d.]+)px/);
    expect(size).not.toBeNull();
    expect(Number(size![1])).toBeGreaterThanOrEqual(11);
  });

  it("gives nav items the shared focus ring", () => {
    expect(rule(".nav-item:focus-visible")).toMatch(/outline:\s*2px solid var\(--accent\)/);
  });

  it("draws the select chevron as an icon, not a glyph", () => {
    expect(css).not.toMatch(/content:\s*"[▾›↗]"/);
  });
});
