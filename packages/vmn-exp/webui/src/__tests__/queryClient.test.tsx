import { describe, it, expect } from "vitest";
import { createQueryClient } from "../queryClient";

describe("createQueryClient", () => {
  it("never retries or refetches on focus — polling owns freshness", () => {
    const d = createQueryClient().getDefaultOptions().queries!;
    expect(d.retry).toBe(false);
    expect(d.refetchOnWindowFocus).toBe(false);
  });
});
