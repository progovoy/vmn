import { describe, it, expect, vi, afterEach } from "vitest";
import { post, type HttpError } from "../http";

afterEach(() => vi.unstubAllGlobals());

describe("http errors", () => {
  it("carry the parsed JSON body of a 409", async () => {
    const payload = { rev: 5, body: "theirs", author: "bob" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 409 })));
    const err = (await post("/x", {}).catch((e) => e)) as HttpError;
    expect(err.status).toBe(409);
    expect(err.body).toEqual(payload);
  });
});
