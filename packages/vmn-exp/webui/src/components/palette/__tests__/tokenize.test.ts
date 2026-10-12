import { describe, it, expect } from "vitest";
import { completeToken, quoteArg, stripCliPrefix, tokenize } from "../tokenize";

const values = (text: string) => tokenize(text).map((t) => t.value);

describe("tokenize", () => {
  it("splits on any whitespace and drops empties", () => {
    expect(values("  show\t-v   @54 ")).toEqual(["show", "-v", "@54"]);
    expect(values("   ")).toEqual([]);
  });

  it("keeps single- and double-quoted spans together, without their quotes", () => {
    const toks = tokenize(`list --query 'metrics.loss < 0.3' "a b"`);
    expect(toks.map((t) => t.value)).toEqual(["list", "--query", "metrics.loss < 0.3", "a b"]);
    expect(toks.map((t) => t.quoted)).toEqual([false, false, true, true]);
    expect(toks[2].raw).toBe("'metrics.loss < 0.3'");
  });

  it("joins a quoted span to the text around it", () => {
    expect(values(`note~"x y"z`)).toEqual(["note~x yz"]);
  });

  it("takes an unterminated quote to the end", () => {
    expect(values(`q "abc def`)).toEqual(["q", "abc def"]);
  });
});

describe("stripCliPrefix", () => {
  it.each([
    ["vmn-exp show x", ["show", "x"]],
    ["vmn show x", ["show", "x"]],
    ["exp show x", ["show", "x"]],
    ["experiment show x", ["show", "x"]],
    ["vmn-exp exp show x", ["show", "x"]],
    ["show vmn", ["show", "vmn"]],
  ])("%s", (text, want) => {
    expect(stripCliPrefix(tokenize(text)).map((t) => t.value)).toEqual(want);
  });
});

describe("quoteArg", () => {
  it("leaves safe words alone and single-quotes the rest", () => {
    expect(quoteArg("ml_app")).toBe("ml_app");
    expect(quoteArg("@54")).toBe("@54");
    expect(quoteArg("0.2.0-dev.1+a")).toBe("0.2.0-dev.1+a");
    expect(quoteArg("a b")).toBe("'a b'");
    expect(quoteArg("it's")).toBe(`'it'\\''s'`);
    expect(quoteArg("")).toBe("''");
  });
});

describe("completeToken", () => {
  it("completes a unique prefix of the last token and adds a space", () => {
    expect(completeToken("sh", ["show", "status"])).toBe("show ");
    expect(completeToken("show ml_", ["ml_app", "other"])).toBe("show ml_app ");
  });

  it("extends to the longest common prefix of several matches", () => {
    expect(completeToken("s", ["stuck", "stuff"])).toBe("stu");
  });

  it("returns null with nothing to complete", () => {
    expect(completeToken("", ["show"])).toBeNull();
    expect(completeToken("show ", ["show"])).toBeNull();
    expect(completeToken("zz", ["show"])).toBeNull();
    expect(completeToken("show", ["show"])).toBeNull();
    expect(completeToken("s", ["show", "status"])).toBeNull();
  });
});
