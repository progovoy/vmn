import { describe, it, expect, vi, afterEach } from "vitest";
import { get, type HttpError } from "../http";

afterEach(() => vi.unstubAllGlobals());

async function failWith(body: unknown, status: number): Promise<HttpError> {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })));
  return (await get("/x").catch((e) => e)) as HttpError;
}

describe("http error code", () => {
  it("is the body's code", async () => {
    const err = await failWith({ detail: "gone", code: "run_not_found", reason: "other" }, 404);
    expect(err.code).toBe("run_not_found");
  });

  it("falls back to the body's reason", async () => {
    const err = await failWith({ detail: "Not a git repository", reason: "not_a_repo" }, 409);
    expect(err.code).toBe("not_a_repo");
  });

  it("is undefined when the body names neither", async () => {
    const err = await failWith({ detail: "nope" }, 400);
    expect(err.code).toBeUndefined();
  });
});
