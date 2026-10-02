import { describe, it, expect, vi, afterEach } from "vitest";
import { del } from "../http";

afterEach(() => vi.unstubAllGlobals());

describe("del", () => {
  it("accepts an empty 204 response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(del("/tokens/abc")).resolves.toBeUndefined();
  });
});
