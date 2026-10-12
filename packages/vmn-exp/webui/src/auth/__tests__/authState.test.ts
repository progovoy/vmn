import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { clearUnauthorized, reportUnauthorized, signOut, useAuthState } from "../authState";
import type { Meta } from "../../types";

const TOKEN_HINTS = { token: true, oidc: false, login_url: null };
const SSO_HINTS = { token: true, oidc: true, login_url: "/auth/login" };

const meta = (oidc: boolean): Meta => ({
  version: "0.10.2",
  auth: { enabled: true, token: true, oidc, api_tokens: false, login_url: oidc ? "/auth/login" : null },
});

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  clearUnauthorized();
  fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("authState", () => {
  it("starts with nothing required", () => {
    const { result } = renderHook(() => useAuthState());
    expect(result.current).toEqual({ required: false, hints: null, method: null });
  });

  it("a report requires sign-in and re-renders subscribers", () => {
    const { result } = renderHook(() => useAuthState());
    act(() => reportUnauthorized({ hints: TOKEN_HINTS, method: "GET" }));
    expect(result.current).toEqual({ required: true, hints: TOKEN_HINTS, method: "GET" });
  });

  it("the first report wins: a GET never downgrades a mutation, nor the reverse", () => {
    const { result } = renderHook(() => useAuthState());
    act(() => reportUnauthorized({ hints: TOKEN_HINTS, method: "POST" }));
    act(() => reportUnauthorized({ hints: SSO_HINTS, method: "GET" }));
    expect(result.current).toEqual({ required: true, hints: TOKEN_HINTS, method: "POST" });

    act(() => clearUnauthorized());
    act(() => reportUnauthorized({ hints: null, method: "GET" }));
    act(() => reportUnauthorized({ hints: null, method: "DELETE" }));
    expect(result.current.method).toBe("GET");
  });

  it("clear resets the state", () => {
    const { result } = renderHook(() => useAuthState());
    act(() => reportUnauthorized({ hints: TOKEN_HINTS, method: "GET" }));
    act(() => clearUnauthorized());
    expect(result.current).toEqual({ required: false, hints: null, method: null });
  });
});

describe("signOut", () => {
  it("clears the token and the cache, then requires a GET sign-in", async () => {
    sessionStorage.setItem("vmn_token", "secret");
    const client = new QueryClient();
    client.setQueryData(["meta"], { version: "1" });
    const { result } = renderHook(() => useAuthState());
    await act(() => signOut(client, meta(false)));
    expect(sessionStorage.getItem("vmn_token")).toBeNull();
    expect(client.getQueryData(["meta"])).toBeUndefined();
    expect(result.current).toEqual({ required: true, hints: TOKEN_HINTS, method: "GET" });
  });

  it("posts a raw /auth/logout only with OIDC", async () => {
    await signOut(new QueryClient(), meta(false));
    expect(fetchMock).not.toHaveBeenCalled();

    clearUnauthorized();
    await signOut(new QueryClient(), meta(true));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/auth/logout", { method: "POST", credentials: "same-origin" });
  });

  it("ignores a failing logout request", async () => {
    fetchMock.mockRejectedValue(new TypeError("offline"));
    const { result } = renderHook(() => useAuthState());
    await act(() => signOut(new QueryClient(), meta(true)));
    expect(result.current).toEqual({ required: true, hints: SSO_HINTS, method: "GET" });
  });

  it("without meta signs out with unknown hints", async () => {
    const { result } = renderHook(() => useAuthState());
    await act(() => signOut(new QueryClient()));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current).toEqual({ required: true, hints: null, method: "GET" });
  });
});
