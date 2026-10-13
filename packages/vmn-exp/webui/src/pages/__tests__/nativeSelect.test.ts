import { describe, it, expect, beforeAll } from "vitest";

// A lint-style check over pages/: a native <select> is only ever the styled
// one, sitting directly inside the shared `.select-wrap`. Vitest runs from
// webui/; the specifier is a string so tsc needs no Node types.
type Fs = {
  readdirSync(path: string): string[];
  readFileSync(path: string, encoding: "utf8"): string;
};
const DIR = "src/pages";
let sources: [string, string][] = [];
beforeAll(async () => {
  const fs: Fs = await import(/* @vite-ignore */ "node:fs" as string);
  sources = fs.readdirSync(DIR)
    .filter((f) => f.endsWith(".tsx"))
    .map((f) => [f, fs.readFileSync(`${DIR}/${f}`, "utf8")]);
});

const WRAPPED = /<\w+[^<>]*className="[^"]*\bselect-wrap\b[^"]*"[^<>]*>\s*$/;

/** `file:line` of every <select> not opened right inside a `.select-wrap`. */
function unstyledSelects(file: string, text: string): string[] {
  const found: string[] = [];
  for (const m of text.matchAll(/<select\b/g)) {
    if (!WRAPPED.test(text.slice(0, m.index))) {
      found.push(`${file}:${text.slice(0, m.index).split("\n").length}`);
    }
  }
  return found;
}

describe("pages/ selects", () => {
  it("reads the page sources", () => {
    expect(sources.length).toBeGreaterThan(10);
  });

  it("has no native unstyled select", () => {
    expect(sources.flatMap(([f, t]) => unstyledSelects(f, t))).toEqual([]);
  });

  it("flags a bare select and accepts a wrapped one", () => {
    expect(unstyledSelects("a.tsx", "<div>\n  <select value={x}>")).toEqual(["a.tsx:2"]);
    expect(unstyledSelects("b.tsx", '<div className="select-wrap">\n  <select>')).toEqual([]);
  });
});
