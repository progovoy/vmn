import { describe, it, expect, beforeAll } from "vitest";

// Vitest stubs imported CSS, so read the file from disk (see sidebarCss.test.ts).
type Fs = { readFileSync(path: string, encoding: "utf8"): string };
let css = "";
beforeAll(async () => {
  const fs: Fs = await import(/* @vite-ignore */ "node:fs" as string);
  css = fs.readFileSync("src/components/shell/Crumbs.css", "utf8");
});

/** The declarations of the first rule whose selector list is exactly *selector*. */
function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`(^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`, "m"));
  expect(match, `rule ${selector}`).not.toBeNull();
  return match![2];
}

describe("Crumbs.css", () => {
  it("hides a root that rendered nothing, and the separator after it", () => {
    expect(rule(".crumb-root:empty,\n.crumb-root:empty + .crumb > .crumb-sep")).toMatch(/display:\s*none/);
  });
});
