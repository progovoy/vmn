import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createQueryClient } from "../../../queryClient";

vi.mock("../../../api", () => ({
  api: { experimentsPaged: vi.fn() },
  appTag: (n: string) => n.replaceAll("/", "-"),
}));

import { api } from "../../../api";
import { refQuery, useRefResolution, type RefState } from "../useRefResolution";

const paged = api.experimentsPaged as unknown as ReturnType<typeof vi.fn>;
const rows = (...vs: [number, string, string?][]) => ({
  rows: vs.map(([idx, verstr, name]) => ({ idx, verstr, name: name ?? null })), total: vs.length,
});

const settled = (results: Record<string, RefState>) =>
  Object.values(results).every((r) => r.state !== "pending");

function resolve(refs: string[], app = "ml_app") {
  const client = createQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) =>
    <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return renderHook(() => useRefResolution("w", app, refs), { wrapper });
}

beforeEach(() => vi.clearAllMocks());

describe("refQuery", () => {
  it("ORs the indexes with one prefix match per prefix", () => {
    expect(refQuery(["@3", "@7", "0.2.0"])).toBe('idx in (3, 7) or verstr ~ "0.2.0"');
    expect(refQuery(["0.1", "0.2"])).toBe('verstr ~ "0.1" or verstr ~ "0.2"');
    expect(refQuery(["latest"])).toBe("");
  });
});

describe("useRefResolution", () => {
  it("resolves every ref of a command in one request, archived runs included", async () => {
    paged.mockResolvedValue(rows([3, "0.1.0-dev.a", "lr-3"], [7, "0.1.0-dev.b"], [9, "0.2.0-dev.c"]));
    const { result } = resolve(["@3", "@7", "0.2.0"]);
    expect(result.current["@3"]).toEqual({ state: "pending" });
    await waitFor(() => expect(settled(result.current)).toBe(true));
    expect(paged).toHaveBeenCalledTimes(1);
    expect(paged).toHaveBeenCalledWith("w", "ml_app", {
      query: 'idx in (3, 7) or verstr ~ "0.2.0"', limit: 23, archived: true,
    });
    expect(result.current).toEqual({
      "@3": { state: "ok", run: { verstr: "0.1.0-dev.a", idx: 3, name: "lr-3" } },
      "@7": { state: "ok", run: { verstr: "0.1.0-dev.b", idx: 7, name: null } },
      "0.2.0": { state: "ok", run: { verstr: "0.2.0-dev.c", idx: 9, name: null } },
    });
  });

  it("keeps only rows the prefix starts, not ones it merely appears in", async () => {
    paged.mockResolvedValue(rows([1, "1.0.2-dev.e"]));
    const { result } = resolve(["0.2"]);
    await waitFor(() => expect(settled(result.current)).toBe(true));
    expect(result.current["0.2"]).toEqual({ state: "none" });
  });

  it("reports a prefix that matches several runs, unless one is exact", async () => {
    paged.mockResolvedValue(rows([1, "0.2.0-dev.c"], [2, "0.2.1-dev.d"], [3, "0.2.0"]));
    const { result } = resolve(["0.2", "0.2.0"]);
    await waitFor(() => expect(settled(result.current)).toBe(true));
    expect(result.current["0.2"]).toEqual({ state: "several" });
    expect(result.current["0.2.0"]).toEqual({ state: "ok", run: { verstr: "0.2.0", idx: 3, name: null } });
  });

  it("finds no run for an index the request did not return", async () => {
    paged.mockResolvedValue(rows([3, "0.1.0-dev.a"]));
    const { result } = resolve(["@3", "@540"]);
    await waitFor(() => expect(settled(result.current)).toBe(true));
    expect(result.current["@540"]).toEqual({ state: "none" });
  });

  it("resolves latest from the index: the newest run, archived included", async () => {
    paged.mockResolvedValue(rows([12, "0.3.0-dev.z"]));
    const { result } = resolve(["latest"], "root/svc");
    await waitFor(() => expect(settled(result.current)).toBe(true));
    expect(paged).toHaveBeenCalledTimes(1);
    expect(paged).toHaveBeenCalledWith("w", "root/svc", { last: 1, limit: 1, archived: true });
    expect(result.current.latest).toEqual({
      state: "ok", run: { verstr: "0.3.0-dev.z", idx: 12, name: null },
    });
  });

  it("finds no latest run in an app without runs", async () => {
    paged.mockResolvedValue(rows());
    const { result } = resolve(["latest"]);
    await waitFor(() => expect(settled(result.current)).toBe(true));
    expect(result.current.latest).toEqual({ state: "none" });
  });

  it("asks nothing without refs", async () => {
    const { result } = resolve([]);
    await new Promise((r) => setTimeout(r, 200));
    expect(result.current).toEqual({});
    expect(paged).not.toHaveBeenCalled();
  });
});
