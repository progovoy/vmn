import { describe, it, expect } from "vitest";
import { parseInline } from "../inline";

describe("parseInline", () => {
  it("parses plain text", () => {
    expect(parseInline("hello")).toEqual([{ type: "text", value: "hello" }]);
  });

  it("parses emphasis, strong and strikethrough", () => {
    expect(parseInline("*a* **b** ~~c~~ _d_ __e__")).toEqual([
      { type: "emphasis", children: [{ type: "text", value: "a" }] },
      { type: "text", value: " " },
      { type: "strong", children: [{ type: "text", value: "b" }] },
      { type: "text", value: " " },
      { type: "delete", children: [{ type: "text", value: "c" }] },
      { type: "text", value: " " },
      { type: "emphasis", children: [{ type: "text", value: "d" }] },
      { type: "text", value: " " },
      { type: "strong", children: [{ type: "text", value: "e" }] },
    ]);
  });

  it("nests emphasis inside strong", () => {
    expect(parseInline("**a *b* c**")).toEqual([
      {
        type: "strong",
        children: [
          { type: "text", value: "a " },
          { type: "emphasis", children: [{ type: "text", value: "b" }] },
          { type: "text", value: " c" },
        ],
      },
    ]);
  });

  it("keeps unmatched delimiters and intraword underscores literal", () => {
    expect(parseInline("2 * 3 and snake_case_name **open")).toEqual([
      { type: "text", value: "2 * 3 and snake_case_name **open" },
    ]);
  });

  it("parses inline code without interpreting its content", () => {
    expect(parseInline("run `a *b* [c](d)` now")).toEqual([
      { type: "text", value: "run " },
      { type: "code", value: "a *b* [c](d)" },
      { type: "text", value: " now" },
    ]);
  });

  it("honours backslash escapes", () => {
    expect(parseInline("\\*not em\\*")).toEqual([{ type: "text", value: "*not em*" }]);
  });

  it("parses links with titles and nested emphasis", () => {
    expect(parseInline('[**x**](https://e.com "T")')).toEqual([
      { type: "link", href: "https://e.com", children: [{ type: "strong", children: [{ type: "text", value: "x" }] }] },
    ]);
  });

  it("parses images", () => {
    expect(parseInline("![alt *t*](vmn://a/v/m.png)")).toEqual([
      { type: "image", src: "vmn://a/v/m.png", alt: "alt t" },
    ]);
  });

  it("parses autolinks", () => {
    expect(parseInline("<https://e.com>")).toEqual([
      { type: "link", href: "https://e.com", children: [{ type: "text", value: "https://e.com" }] },
    ]);
  });

  it("keeps raw HTML as text", () => {
    expect(parseInline("<b>hi</b>")).toEqual([{ type: "text", value: "<b>hi</b>" }]);
  });

  it("turns trailing double space and backslash into hard breaks", () => {
    expect(parseInline("a  \nb\\\nc\nd")).toEqual([
      { type: "text", value: "a" },
      { type: "break" },
      { type: "text", value: "b" },
      { type: "break" },
      { type: "text", value: "c\nd" },
    ]);
  });

  it("leaves a bracket without destination literal", () => {
    expect(parseInline("[x] and [y](")).toEqual([{ type: "text", value: "[x] and [y](" }]);
  });
});
