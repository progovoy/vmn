import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("../api", () => ({
  api: {
    facets: vi.fn(),
    metricsSchema: vi.fn(),
    apps: vi.fn(),
    workspaces: vi.fn(),
    experiment: vi.fn(),
  },
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { api } from "../api";
import { createQueryClient } from "../queryClient";
import {
  findCachedRow, prefetchRun, rowsKey, useApps, useFacets, useMetricsSchema,
} from "../queries";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function wrap() {
  const client = createQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

beforeEach(() => vi.clearAllMocks());

describe("shared resources", () => {
  it("fetch once across components and mounts (60s fresh)", async () => {
    m.apps.mockResolvedValue([{ name: "a", experiments: 1, versions: 0 }]);
    const { wrapper } = wrap();
    const one = renderHook(() => useApps("w"), { wrapper });
    await waitFor(() => expect(one.result.current.data).toHaveLength(1));
    one.unmount();
    const two = renderHook(() => useApps("w"), { wrapper });
    expect(two.result.current.data).toHaveLength(1);
    expect(m.apps).toHaveBeenCalledTimes(1);
  });

  it("metrics schema falls back to {} when the request fails", async () => {
    m.metricsSchema.mockRejectedValue(new Error("nope"));
    const { wrapper } = wrap();
    const { result } = renderHook(() => useMetricsSchema("w", "app"), { wrapper });
    await waitFor(() => expect(result.current).toEqual({}));
  });
});

describe("useFacets", () => {
  it("returns the server's facets", async () => {
    m.facets.mockResolvedValue({ branches: ["main"], metric_keys: [], param_keys: [], total: 1 });
    const { wrapper } = wrap();
    const { result } = renderHook(() => useFacets("w", "app"), { wrapper });
    await waitFor(() => expect(result.current?.branches).toEqual(["main"]));
  });

  it("degrades to null when the endpoint is missing (404)", async () => {
    m.facets.mockRejectedValue(Object.assign(new Error("Not Found"), { status: 404 }));
    const { wrapper } = wrap();
    const { result } = renderHook(() => useFacets("w", "app"), { wrapper });
    await waitFor(() => expect(m.facets).toHaveBeenCalled());
    expect(result.current).toBeNull();
  });
});

describe("run cache helpers", () => {
  it("findCachedRow finds a leaderboard row by verstr in any cached list", () => {
    const { client } = wrap();
    client.setQueryData(rowsKey("w", "app", { status: "running" }), {
      rows: [{ verstr: "v1", note: "hi" }], total: 1,
    });
    expect(findCachedRow(client, "w", "app", "v1")).toMatchObject({ note: "hi" });
    expect(findCachedRow(client, "w", "app", "nope")).toBeUndefined();
    expect(findCachedRow(client, "w", "other", "v1")).toBeUndefined();
  });

  it("prefetchRun loads the detail once while it is fresh", async () => {
    m.experiment.mockResolvedValue({ metadata: { verstr: "v1" } });
    const { client } = wrap();
    await prefetchRun(client, "w", "app", "v1");
    await prefetchRun(client, "w", "app", "v1");
    expect(m.experiment).toHaveBeenCalledTimes(1);
    expect(m.experiment).toHaveBeenCalledWith("w", "app", "v1");
  });
});
