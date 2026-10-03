import { describe, it, expect } from "vitest";
import { parseBlocks } from "../block";

const t = (value: string) => [{ type: "text", value }];

describe("parseBlocks", () => {
  it("parses ATX headings with closing hashes", () => {
    expect(parseBlocks("# One\n### Three ###\n#nope")).toEqual([
      { type: "heading", depth: 1, children: t("One") },
      { type: "heading", depth: 3, children: t("Three") },
      { type: "paragraph", children: t("#nope") },
    ]);
  });

  it("parses setext headings", () => {
    expect(parseBlocks("Intro\n=====\n\nSub\n---")).toEqual([
      { type: "heading", depth: 1, children: t("Intro") },
      { type: "heading", depth: 2, children: t("Sub") },
    ]);
  });

  it("joins paragraph lines and splits on blank lines", () => {
    expect(parseBlocks("a\nb\n\nc")).toEqual([
      { type: "paragraph", children: t("a\nb") },
      { type: "paragraph", children: t("c") },
    ]);
  });

  it("parses fenced code blocks verbatim", () => {
    expect(parseBlocks("```py\n# not a heading\n  x = 1\n```\nafter")).toEqual([
      { type: "code", lang: "py", value: "# not a heading\n  x = 1\n" },
      { type: "paragraph", children: t("after") },
    ]);
  });

  it("runs an unclosed fence to the end", () => {
    expect(parseBlocks("~~~\na")).toEqual([{ type: "code", lang: "", value: "a\n" }]);
  });

  it("parses horizontal rules", () => {
    expect(parseBlocks("a\n\n***\n\n- - -")).toEqual([
      { type: "paragraph", children: t("a") },
      { type: "hr" },
      { type: "hr" },
    ]);
  });

  it("parses blockquotes recursively", () => {
    expect(parseBlocks("> # T\n> body")).toEqual([
      {
        type: "blockquote",
        children: [
          { type: "heading", depth: 1, children: t("T") },
          { type: "paragraph", children: t("body") },
        ],
      },
    ]);
  });

  it("parses tight unordered lists with nesting", () => {
    expect(parseBlocks("- a\n- b\n  - c\n* other")).toEqual([
      {
        type: "list",
        ordered: false,
        start: 1,
        tight: true,
        items: [
          [{ type: "paragraph", children: t("a") }],
          [
            { type: "paragraph", children: t("b") },
            { type: "list", ordered: false, start: 1, tight: true, items: [[{ type: "paragraph", children: t("c") }]] },
          ],
        ],
      },
      { type: "list", ordered: false, start: 1, tight: true, items: [[{ type: "paragraph", children: t("other") }]] },
    ]);
  });

  it("parses loose ordered lists with a start number", () => {
    expect(parseBlocks("3. x\n\n4. y")).toEqual([
      {
        type: "list",
        ordered: true,
        start: 3,
        tight: false,
        items: [[{ type: "paragraph", children: t("x") }], [{ type: "paragraph", children: t("y") }]],
      },
    ]);
  });

  it("parses GFM tables with alignment and escaped pipes", () => {
    expect(parseBlocks("| a | b | c |\n|:--|:-:|--:|\n| 1 | x\\|y |\n\nend")).toEqual([
      {
        type: "table",
        align: ["left", "center", "right"],
        head: [t("a"), t("b"), t("c")],
        rows: [[t("1"), t("x|y"), []]],
      },
      { type: "paragraph", children: t("end") },
    ]);
  });

  it("does not treat a pipe line without delimiter row as a table", () => {
    expect(parseBlocks("a | b\nc")).toEqual([{ type: "paragraph", children: t("a | b\nc") }]);
  });

  it("lets block starts interrupt a paragraph", () => {
    expect(parseBlocks("para\n# H\n```\nc\n```")).toEqual([
      { type: "paragraph", children: t("para") },
      { type: "heading", depth: 1, children: t("H") },
      { type: "code", lang: "", value: "c\n" },
    ]);
  });
});
