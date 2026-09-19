import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useFetch } from "../useFetch";

describe("useFetch", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("returns loading then data", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ items: [1, 2] }), { status: 200 })
    );
    const { result } = renderHook(() => useFetch<{items: number[]}>("/test"));
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toEqual({ items: [1, 2] });
    expect(result.current.error).toBeNull();
  });

  it("returns error on failure", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("network"));
    const { result } = renderHook(() => useFetch("/fail"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeTruthy();
    expect(result.current.data).toBeNull();
  });

  it("skips fetch when url is null", () => {
    const spy = vi.spyOn(globalThis, "fetch");
    renderHook(() => useFetch(null));
    expect(spy).not.toHaveBeenCalled();
  });

  it("aborts previous request on URL change", async () => {
    const abortSpy = vi.fn();
    vi.spyOn(globalThis, "AbortController").mockImplementation(() => ({
      signal: { aborted: false },
      abort: abortSpy,
    } as any));
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 })
    );
    const { rerender } = renderHook(
      ({ url }) => useFetch(url),
      { initialProps: { url: "/a" } }
    );
    rerender({ url: "/b" });
    expect(abortSpy).toHaveBeenCalled();
  });
});
