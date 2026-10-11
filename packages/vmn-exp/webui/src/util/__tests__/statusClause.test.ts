import { describe, it, expect } from "vitest";
import { statusClause } from "../searchQuery";

describe("statusClause", () => {
  it("turns the ?status= CSV into the query language's in clause", () => {
    expect(statusClause("succeeded,failed")).toBe('status in ("succeeded", "failed")');
  });

  it("is null for no status", () => {
    expect(statusClause("")).toBeNull();
    expect(statusClause(undefined)).toBeNull();
  });
});
