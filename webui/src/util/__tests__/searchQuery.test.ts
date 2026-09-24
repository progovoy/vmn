import { describe, it, expect } from "vitest";
import { verstrInQuery } from "../searchQuery";

describe("verstrInQuery", () => {
  it("builds the query language's `in` clause", () => {
    expect(verstrInQuery(["a", "0.0.1-dev.x"])).toBe('verstr in ("a", "0.0.1-dev.x")');
  });
});
