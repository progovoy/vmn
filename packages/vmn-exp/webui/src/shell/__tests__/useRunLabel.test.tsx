import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createQueryClient } from "../../queryClient";

const experiment = vi.fn();
const experiments = vi.fn();
vi.mock("../../api", () => ({
  api: { experiment: (...a: unknown[]) => experiment(...a), experiments: (...a: unknown[]) => experiments(...a) },
}));

import { rowsKey, runKey } from "../../queries";
import { useRunLabel } from "../useRunLabel";

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) =>
  <QueryClientProvider client={client}>{children}</QueryClientProvider>;
const label = (verstr?: string) =>
  renderHook(() => useRunLabel("ml-repo", "ml_app", verstr), { wrapper });

describe("useRunLabel", () => {
  beforeEach(() => {
    client = createQueryClient();
    experiment.mockReset();
    experiments.mockReset();
  });

  it("reads idx and name from the cached detail first", () => {
    client.setQueryData(runKey("ml-repo", "ml_app", "@54"), {
      metadata: { verstr: "0.4.1-dev.abc" }, idx: 54, name: "lr-sweep-3",
    });
    client.setQueryData(rowsKey("ml-repo", "ml_app", {}), {
      rows: [{ verstr: "0.4.1-dev.abc", idx: 9, name: "other" }], total: 1,
    });
    expect(label("@54").result.current).toEqual({ verstr: "0.4.1-dev.abc", idx: 54, name: "lr-sweep-3" });
  });

  it("falls back to a cached leaderboard row", () => {
    client.setQueryData(rowsKey("ml-repo", "ml_app", { status: "running" }), {
      rows: [{ verstr: "0.4.1-dev.abc", idx: 3, name: null }], total: 1,
    });
    expect(label("0.4.1-dev.abc").result.current).toEqual({ verstr: "0.4.1-dev.abc", idx: 3, name: null });
  });

  it("uses the row when the detail carries no idx (an older server)", () => {
    client.setQueryData(runKey("ml-repo", "ml_app", "0.4.1-dev.abc"), { metadata: { verstr: "0.4.1-dev.abc" } });
    client.setQueryData(rowsKey("ml-repo", "ml_app", {}), {
      rows: [{ verstr: "0.4.1-dev.abc", idx: 3, name: "r" }], total: 1,
    });
    expect(label("0.4.1-dev.abc").result.current).toEqual({ verstr: "0.4.1-dev.abc", idx: 3, name: "r" });
  });

  it("is undefined when nothing is cached, and never fetches", () => {
    const { result } = label("0.4.1-dev.abc");
    expect(result.current).toBeUndefined();
    expect(label(undefined).result.current).toBeUndefined();
    expect(experiment).not.toHaveBeenCalled();
    expect(experiments).not.toHaveBeenCalled();
  });

  it("follows the cache as the detail lands", () => {
    const { result } = label("@7");
    expect(result.current).toBeUndefined();
    act(() => {
      client.setQueryData(runKey("ml-repo", "ml_app", "@7"), { metadata: { verstr: "v7" }, idx: 7, name: null });
    });
    expect(result.current).toEqual({ verstr: "v7", idx: 7, name: null });
    expect(experiment).not.toHaveBeenCalled();
  });
});
