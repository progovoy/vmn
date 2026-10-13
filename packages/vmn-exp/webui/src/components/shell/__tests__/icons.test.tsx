import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Icon, ICON_NAMES } from "../icons";

const NAMES = [
  "experiments", "tree", "actions", "apps", "models", "reports", "key", "menu", "search",
  "copy", "check", "chevron-down", "chevron-right", "chevron-left", "external", "close",
  "theme-system", "sun", "moon", "run", "app", "workspace", "store", "page", "command",
] as const;

const svgOf = (name: (typeof NAMES)[number], size?: number) =>
  render(<Icon name={name} size={size} />).container.querySelector("svg")!;

describe("Icon", () => {
  it("covers exactly the contract's names", () => {
    expect([...ICON_NAMES].sort()).toEqual([...NAMES].sort());
  });

  it("draws a distinct path for every name", () => {
    const drawings = NAMES.map((n) =>
      [...svgOf(n).querySelectorAll("path")].map((p) => p.getAttribute("d")).join(" "));
    drawings.forEach((d) => expect(d.trim()).not.toBe(""));
    expect(new Set(drawings).size).toBe(NAMES.length);
  });

  it.each(NAMES)("%s follows the icon rule", (name) => {
    const svg = svgOf(name);
    expect(svg.getAttribute("viewBox")).toBe("0 0 15 15");
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    expect(svg.getAttribute("focusable")).toBe("false");
    expect(svg.getAttribute("stroke")).toBe("currentColor");
    expect(svg.getAttribute("stroke-width")).toBe("1.6");
    expect(svg.getAttribute("fill")).toBe("none");
    expect(svg.textContent).toBe("");
  });

  it("is 15 px unless sized", () => {
    expect(svgOf("menu").getAttribute("width")).toBe("15");
    const small = svgOf("chevron-right", 11);
    expect(small.getAttribute("width")).toBe("11");
    expect(small.getAttribute("height")).toBe("11");
  });
});
