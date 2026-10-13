import { describe, it, expect } from "vitest";
import { searchClause, verstrInQuery } from "../searchQuery";

describe("verstrInQuery", () => {
  it("builds the query language's `in` clause", () => {
    expect(verstrInQuery(["a", "0.0.1-dev.x"])).toBe('verstr in ("a", "0.0.1-dev.x")');
  });
});

describe("searchClause (plan 20 D10)", () => {
  it("matches the text in the run's name, verstr, note and branch", () => {
    expect(searchClause("bat")).toBe('name ~ "bat" or verstr ~ "bat" or note ~ "bat" or branch ~ "bat"');
  });

  it("quotes text holding a double quote with single quotes", () => {
    expect(searchClause('say "hi"')).toBe(
      "name ~ 'say \"hi\"' or verstr ~ 'say \"hi\"' or note ~ 'say \"hi\"' or branch ~ 'say \"hi\"'",
    );
  });
});
