import { describe, it, expect } from "vitest";
import { midTruncate } from "../midTruncate";

describe("midTruncate", () => {
  it("keeps text that fits", () => {
    expect(midTruncate("0.1.0", 24)).toBe("0.1.0");
    expect(midTruncate("x".repeat(24), 24)).toBe("x".repeat(24));
  });

  it("keeps the head and the last 8 chars around an ellipsis", () => {
    const out = midTruncate("0.0.1-dev.e71c74d.9f3a1b2c4d5e", 24);
    expect(out).toBe("0.0.1-dev.e71c7…1b2c4d5e");
    expect(out).toHaveLength(24);
  });

  it("keeps only the tail when max leaves no room for a head", () => {
    expect(midTruncate("abcdefghijklmnop", 9)).toBe("…ijklmnop");
  });
});
