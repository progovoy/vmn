import { describe, it, expect, beforeAll } from "vitest";

// Vitest stubs imported CSS, so read the file from disk (see sidebarCss.test.ts).
type Fs = { readFileSync(path: string, encoding: "utf8"): string };
let css = "";
beforeAll(async () => {
  const fs: Fs = await import(/* @vite-ignore */ "node:fs" as string);
  css = fs.readFileSync("src/components/shell/Provenance.css", "utf8");
});

/** The body of the `@media (max-width: 899px)` block (the mobile drawer). */
function narrowBlock(): string {
  const start = css.indexOf("@media (max-width: 899px)");
  expect(start, "narrow media block").toBeGreaterThanOrEqual(0);
  return css.slice(start);
}

/** The declarations of the first rule in *body* whose selector is exactly *selector*. */
function rule(body: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = body.match(new RegExp(`(^|[{}])\\s*${escaped}\\s*\\{([^}]*)\\}`, "m"));
  expect(match, `rule ${selector}`).not.toBeNull();
  return match![2];
}

describe("Provenance.css in the mobile drawer", () => {
  it("anchors the popover to the drawer's context block, not the icon button", () => {
    const narrow = narrowBlock();
    expect(rule(narrow, ".drawer-context")).toMatch(/position:\s*relative/);
    expect(rule(narrow, ".drawer-context .prov")).toMatch(/position:\s*static/);
  });

  it("fits the popover inside the 280px drawer", () => {
    const pop = rule(narrowBlock(), ".drawer-context .prov-pop");
    expect(pop).toMatch(/left:\s*18px/);
    expect(pop).toMatch(/right:\s*18px/);
    expect(pop).toMatch(/min-width:\s*0/);
    expect(pop).toMatch(/max-width:\s*none/);
  });

  it("lets the drawer's context root wrap instead of running past the edge", () => {
    expect(rule(narrowBlock(), ".drawer-context .ctx-root")).toMatch(/flex-wrap:\s*wrap/);
  });
});
