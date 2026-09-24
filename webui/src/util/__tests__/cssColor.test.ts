import { describe, it, expect } from "vitest";
import { chartTheme, resolveCssColor } from "../cssColor";

const vars: Record<string, string> = {
  "--minor": " #4d8df6",
  "--series-1": "var(--minor)",
  "--text-3": "#85847a",
  "--line": "#2b2b27",
  "--text-2": "#b6b5aa",
};
const read = (name: string) => vars[name] ?? "";

describe("resolveCssColor", () => {
  it("passes a literal colour through", () => {
    expect(resolveCssColor("hsl(10, 65%, 55%)", read)).toBe("hsl(10, 65%, 55%)");
  });

  it("resolves a var() reference, recursively and trimmed", () => {
    expect(resolveCssColor("var(--minor)", read)).toBe("#4d8df6");
    expect(resolveCssColor("var(--series-1)", read)).toBe("#4d8df6");
  });

  it("uses the var()'s own fallback, then a neutral grey", () => {
    expect(resolveCssColor("var(--nope, #123456)", read)).toBe("#123456");
    expect(resolveCssColor("var(--nope)", read)).toBe("#888888");
  });
});

describe("chartTheme", () => {
  it("reads axis, grid and text colours from the design variables", () => {
    expect(chartTheme(read)).toEqual({ axis: "#85847a", grid: "#2b2b27", text: "#b6b5aa" });
  });
});
