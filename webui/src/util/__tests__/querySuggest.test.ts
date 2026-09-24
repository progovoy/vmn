import { describe, it, expect } from "vitest";
import { applySuggestion, suggest } from "../querySuggest";

const facets = { metric_keys: ["loss", "acc"], param_keys: ["lr", "model"] };

describe("suggest", () => {
  it("offers metric, param and row fields at the start", () => {
    const s = suggest("", 0, facets);
    expect(s).toContain("metrics.loss");
    expect(s).toContain("params.model");
    expect(s).toContain("status");
  });

  it("narrows fields by the word being typed", () => {
    const s = suggest("metrics.l", 9, facets);
    expect(s).toEqual(["metrics.loss"]);
  });

  it("matches a param name typed without its prefix", () => {
    expect(suggest("mod", 3, facets)).toContain("params.model");
  });

  it("offers operators after a field", () => {
    const s = suggest("metrics.loss ", 13, facets);
    expect(s).toEqual(expect.arrayContaining(["<", ">=", "=", "~", "in"]));
    expect(s).not.toContain("metrics.acc");
  });

  it("offers and/or after a value", () => {
    expect(suggest("metrics.loss < 0.5 ", 19, facets)).toEqual(["and", "or"]);
    expect(suggest('note ~ "x" ', 11, facets)).toEqual(["and", "or"]);
  });

  it("offers fields again after and", () => {
    expect(suggest("metrics.loss < 0.5 and ", 23, facets)).toContain("params.lr");
  });

  it("offers nothing while typing a value", () => {
    expect(suggest("metrics.loss < 0.", 17, facets)).toEqual([]);
  });
});

describe("applySuggestion", () => {
  it("replaces the word at the caret and adds a space", () => {
    expect(applySuggestion("metrics.l", 9, "metrics.loss")).toEqual({
      text: "metrics.loss ", caret: 13,
    });
  });

  it("appends after a space", () => {
    expect(applySuggestion("metrics.loss ", 13, "<")).toEqual({
      text: "metrics.loss < ", caret: 15,
    });
  });

  it("keeps the text after the caret", () => {
    expect(applySuggestion("sta and x", 3, "status").text).toBe("status  and x");
  });
});
