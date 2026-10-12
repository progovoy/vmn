/** The dashboard works on an air-gapped box (plan 19 §1.11): fonts ship in
 *  the bundle, and the page names the product. */
import { describe, it, expect, beforeAll } from "vitest";

type Fs = { readFileSync(path: string, encoding: "utf8"): string };
const files: Record<string, string> = {};
beforeAll(async () => {
  const fs: Fs = await import(/* @vite-ignore */ "node:fs" as string);
  for (const path of ["index.html", "src/main.tsx", "vite.export.config.ts", "src/styles.css",
    "src/components/shell/Sidebar.css"]) {
    files[path] = fs.readFileSync(path, "utf8");
  }
});

describe("index.html", () => {
  it("loads no Google Fonts", () => {
    expect(files["index.html"]).not.toMatch(/fonts\.googleapis|gstatic/);
  });

  it("is titled vmn-exp", () => {
    expect(files["index.html"]).toMatch(/<title>vmn-exp<\/title>/);
  });
});

describe("self-hosted IBM Plex", () => {
  for (const weight of [400, 500, 600, 700]) {
    it(`imports the latin Plex Sans ${weight}`, () => {
      expect(files["src/main.tsx"]).toContain(`import "@fontsource/ibm-plex-sans/latin-${weight}.css";`);
    });
  }
  for (const weight of [400, 500, 600]) {
    it(`imports the latin Plex Mono ${weight}`, () => {
      expect(files["src/main.tsx"]).toContain(`import "@fontsource/ibm-plex-mono/latin-${weight}.css";`);
    });
  }

  it("keeps the report export build off Google too", () => {
    expect(files["vite.export.config.ts"]).not.toMatch(/googleapis|gstatic/);
  });
});

describe("shell CSS", () => {
  it("has one shared .sr-only rule, in styles.css", () => {
    expect(files["src/styles.css"]).toMatch(/(^|\n)\.sr-only\s*\{/);
    expect(files["src/components/shell/Sidebar.css"]).not.toMatch(/\.sr-only\s*\{/);
  });

  it("styles the skip link, the drawer veil and the drawer context", () => {
    for (const sel of [".skip-link", ".drawer-veil", ".drawer-context"]) {
      expect(files["src/styles.css"]).toContain(sel);
    }
  });

  it("drops the shell rules the unit components replaced", () => {
    for (const gone of [
      /\.sb-[a-z]/, /\.crumbs\b/, /\.host-chip/, /\.search-pill/, /\.palette/,
      /\.theme-toggle/, /(^|\n)\.grid\s*\{/, /(^|\n)\.tile\b/, /\.status-dot/,
    ]) {
      expect(files["src/styles.css"]).not.toMatch(gone);
    }
  });

  it("themes text selection from the accent", () => {
    expect(files["src/styles.css"]).toMatch(/::selection\s*\{[^}]*var\(--accent\)/);
  });
});
