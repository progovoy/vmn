import { describe, it, expect } from "vitest";
import { parseYamlLite } from "../yamlLite";

describe("parseYamlLite", () => {
  it("parses flat mappings with typed scalars", () => {
    expect(parseYamlLite("a: 1\nb: -2.5e3\nc: true\nd: False\ne: null\nf: ~\ng:\nh: text here\n")).toEqual({
      a: 1, b: -2500, c: true, d: false, e: null, f: null, g: null, h: "text here",
    });
  });

  it("parses quoted scalars", () => {
    expect(parseYamlLite(`a: "x: #1\\n"\nb: 'it''s'\nc: "42"`)).toEqual({ a: "x: #1\n", b: "it's", c: "42" });
  });

  it("strips comments outside quotes", () => {
    expect(parseYamlLite("# head\na: 1 # one\nb: x#y\n  # indented comment\nc: 'q # not'")).toEqual({
      a: 1, b: "x#y", c: "q # not",
    });
  });

  it("parses nested mappings", () => {
    expect(parseYamlLite("v: 1\nruns:\n  query: metrics.acc > 0.9\n  sort: acc\n  deep:\n    k: v\nid: p")).toEqual({
      v: 1, runs: { query: "metrics.acc > 0.9", sort: "acc", deep: { k: "v" } }, id: "p",
    });
  });

  it("parses block sequences, including mapping items and same-indent lists", () => {
    expect(parseYamlLite("keys:\n  - loss\n  - 2\nitems:\n- a: 1\n  b: 2\n- c: 3\n")).toEqual({
      keys: ["loss", 2], items: [{ a: 1, b: 2 }, { c: 3 }],
    });
  });

  it("parses flow sequences and mappings", () => {
    expect(parseYamlLite('metrics: [loss, "a,b", 3, [x]]\nx: {mode: metric, metric: "step", n: 2}\ne: []\nf: {}')).toEqual({
      metrics: ["loss", "a,b", 3, ["x"]], x: { mode: "metric", metric: "step", n: 2 }, e: [], f: {},
    });
  });

  it("parses a top-level sequence and scalar", () => {
    expect(parseYamlLite("- 1\n- two")).toEqual([1, "two"]);
    expect(parseYamlLite("hello")).toBe("hello");
    expect(parseYamlLite("")).toBeNull();
  });

  it("keeps colons without a following space in plain scalars", () => {
    expect(parseYamlLite("url: http://x.com/a\nt: 12:30")).toEqual({ url: "http://x.com/a", t: "12:30" });
  });

  it.each([
    ["id: [unclosed", /unclosed|unterminated|expected/i],
    ["a: {b: 1", /unclosed|unterminated|expected/i],
    ["a: |\n  text", /unsupported/i],
    ["a: &x 1", /unsupported/i],
    ["a: !tag 1", /unsupported/i],
    ["a: 1\na: 2", /duplicate/i],
    ["a: 1\n   b: 2", /indent/i],
    ["a: 'open", /unterminated|unclosed/i],
    ["a: 1\n- b", /line 2/i],
    ["\ta: 1", /tab/i],
  ])("rejects %j", (src, msg) => {
    expect(() => parseYamlLite(src)).toThrow(msg);
  });
});
