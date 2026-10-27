import { describe, it, expect, beforeAll } from "vitest";

// Vitest stubs imported CSS, so read the files from disk (see crumbsCss.test.ts).
type Fs = { readFileSync(path: string, encoding: "utf8"): string };
let topbar = "";
let crumbs = "";
beforeAll(async () => {
  const fs: Fs = await import(/* @vite-ignore */ "node:fs" as string);
  topbar = fs.readFileSync("src/components/shell/Topbar.css", "utf8");
  crumbs = fs.readFileSync("src/components/shell/Crumbs.css", "utf8");
});

/** The declarations of the first rule of *css* whose selector list is exactly *selector*. */
function rule(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`(^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`, "m"));
  expect(match, `rule ${selector}`).not.toBeNull();
  return match![2];
}

describe("a long workspace name in the trail", () => {
  // A 33-character store name drew over the app crumb and the store icon.
  it("is cut with an ellipsis instead of overflowing its crumb", () => {
    const ws = rule(topbar, ".ctx-ws");
    expect(ws).toMatch(/min-width:\s*0/);
    expect(ws).toMatch(/overflow:\s*hidden/);
    expect(ws).toMatch(/text-overflow:\s*ellipsis/);
  });

  it("leaves the app and page crumbs room", () => {
    expect(rule(crumbs, ".crumb-root")).toMatch(/max-width:\s*40%/);
  });
});
