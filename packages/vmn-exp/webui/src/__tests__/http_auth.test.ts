import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";

const reportUnauthorized = vi.fn();
vi.mock("../auth/authState", () => ({ reportUnauthorized: (a: unknown) => reportUnauthorized(a) }));

import { del, get, patch, post, type HttpError } from "../http";

const HINTS = { token: true, oidc: true, login_url: "/auth/login" };
const BODY = { detail: "Unauthorized", auth: HINTS };

const calls: Record<string, () => Promise<unknown>> = {
  GET: () => get("/meta"),
  POST: () => post("/x", { a: 1 }),
  PATCH: () => patch("/x", { a: 1 }),
  DELETE: () => del("/x"),
};

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  reportUnauthorized.mockReset();
  sessionStorage.setItem("vmn_token", "old");
  fetchMock = vi.fn().mockImplementation(
    async () => new Response(JSON.stringify(BODY), { status: 401 }));
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("prompt", vi.fn(() => "typed"));
});
afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("a 401", () => {
  for (const [method, call] of Object.entries(calls)) {
    it(`on ${method} reports the method and hints, then throws status 401`, async () => {
      const err = (await call().catch((e) => e)) as HttpError;
      expect(err).toBeInstanceOf(Error);
      expect(err.status).toBe(401);
      expect(err.body).toEqual(BODY);
      expect(reportUnauthorized).toHaveBeenCalledTimes(1);
      expect(reportUnauthorized).toHaveBeenCalledWith({ hints: HINTS, method });
    });

    it(`on ${method} never prompts and never replays the request`, async () => {
      await call().catch(() => {});
      expect(window.prompt).not.toHaveBeenCalled();
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(sessionStorage.getItem("vmn_token")).toBe("old");
    });
  }

  it("from an older server without hints reports null hints", async () => {
    fetchMock.mockImplementation(
      async () => new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 }));
    await get("/meta").catch(() => {});
    expect(reportUnauthorized).toHaveBeenCalledWith({ hints: null, method: "GET" });
  });

  it("with a non-JSON body still reports and throws 401", async () => {
    fetchMock.mockImplementation(async () => new Response("nope", { status: 401 }));
    const err = (await post("/x", {}).catch((e) => e)) as HttpError;
    expect(err.status).toBe(401);
    expect(reportUnauthorized).toHaveBeenCalledWith({ hints: null, method: "POST" });
  });
});

describe("other responses", () => {
  it("a 403 is not a sign-in case", async () => {
    fetchMock.mockImplementation(
      async () => new Response(JSON.stringify({ detail: "Requires role 'editor'" }), { status: 403 }));
    const err = (await post("/x", {}).catch((e) => e)) as HttpError;
    expect(err.status).toBe(403);
    expect(err.message).toBe("Requires role 'editor'");
    expect(reportUnauthorized).not.toHaveBeenCalled();
  });

  it("keeps the bearer token, method and JSON body", async () => {
    fetchMock.mockImplementation(async () => new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
    await expect(patch("/x", { a: 1 })).resolves.toEqual({ ok: 1 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/x");
    expect(init.method).toBe("PATCH");
    expect(init.body).toBe('{"a":1}');
    expect(init.headers).toMatchObject({ Authorization: "Bearer old", "Content-Type": "application/json" });
  });
});
