import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createQueryClient, useAppQueryClient } from "../queryClient";

describe("createQueryClient", () => {
  it("never retries or refetches on focus — polling owns freshness", () => {
    const d = createQueryClient().getDefaultOptions().queries!;
    expect(d.retry).toBe(false);
    expect(d.refetchOnWindowFocus).toBe(false);
  });
});

describe("useAppQueryClient", () => {
  it("returns the provided client", () => {
    const client = createQueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useAppQueryClient(), { wrapper });
    expect(result.current).toBe(client);
  });

  it("falls back to one stable client of its own without a provider", () => {
    const { result, rerender } = renderHook(() => useAppQueryClient());
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
