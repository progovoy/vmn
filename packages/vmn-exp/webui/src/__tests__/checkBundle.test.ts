import { describe, it, expect } from "vitest";
import { ENTRY_BUDGET_BYTES, checkEntrySize } from "../../scripts/check-bundle.mjs";

describe("check-bundle (plan 42 E14b)", () => {
  it("fails an entry chunk over the budget and names both sizes", () => {
    const result = checkEntrySize(1001, 1000);
    expect(result.ok).toBe(false);
    expect(result.message).toContain("1001");
    expect(result.message).toContain("1000");
  });

  it("passes an entry chunk at or under the budget", () => {
    expect(checkEntrySize(1000, 1000).ok).toBe(true);
    expect(checkEntrySize(10, 1000).ok).toBe(true);
  });

  it("fails today's 572 KB entry chunk, from before the vendor split", () => {
    expect(checkEntrySize(572317, ENTRY_BUDGET_BYTES).ok).toBe(false);
  });
});
