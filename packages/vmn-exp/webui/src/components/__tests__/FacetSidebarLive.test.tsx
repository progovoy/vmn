/** A live change refreshes the app's facets (useBoardLive): the sidebar
 *  then re-reads its status counts and the filtered facets, but each
 *  param's counts only once the runs they count moved (the filtered total,
 *  or the param's distinct values). */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";

vi.mock("../../api", async (orig) => {
  const actual = await orig<typeof import("../../api")>();
  return { ...actual, api: { facets: vi.fn(), experimentGroups: vi.fn(), experimentsColumns: vi.fn() } };
});

import { api } from "../../api";
import type { GroupOpts } from "../../apiGroups";
import { facetsQuery } from "../../queries";
import { createQueryClient } from "../../queryClient";
import FacetSidebar from "../FacetSidebar";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const group = (key: string, total: number) => ({
  key, label: key, target: null, loose: false, aggregates: {}, rows: [], rows_total: total, rows_unfiltered: total,
  counts: { total, running: 0, waiting: 0, done: total, failed: 0, stuck: 0 }, clause: null,
});
const facets = (total: number) => ({
  branches: [], metric_keys: [], param_keys: ["seed", "opt"], tag_keys: [],
  param_values: { seed: 21, opt: 2 }, parented: 0, jobs: 0, singles: 0, total,
});
const paramGroupCalls = () => m.experimentGroups.mock.calls.filter((c) => (c[2] as GroupOpts).group !== "status").length;

beforeEach(() => {
  vi.clearAllMocks();
  m.facets.mockResolvedValue(facets(40));
  m.experimentGroups.mockImplementation((_w: string, _a: string, o: GroupOpts) => Promise.resolve({
    groups: o.group === "status" ? [group("succeeded", 40)] : [group("adam", 20), group("sgd", 20)],
    total_groups: o.group === "status" ? 1 : 2, total_rows: 40, aggregate: "mean", running: 0,
  }));
  m.experimentsColumns.mockResolvedValue({
    verstrs: [], idx: [], total: 40, columns: { "params.seed": Array.from({ length: 40 }, (_, i) => i) },
  });
});

describe("FacetSidebar under live changes", () => {
  it("re-reads param counts only when the runs they count moved", async () => {
    const client = createQueryClient();
    render(
      <QueryClientProvider client={client}>
        <FacetSidebar ws="w" app="a" scope="J" query="" status="" onAdd={() => {}} />
      </QueryClientProvider>,
    );
    await screen.findByRole("group", { name: "params.seed histogram" });
    await screen.findByRole("list", { name: "params.opt values" });
    expect(m.experimentsColumns).toHaveBeenCalledTimes(1);
    expect(paramGroupCalls()).toBe(1);
    const facetCalls = m.facets.mock.calls.length;

    // A change that moved nothing the params count: no param request.
    await act(() => client.invalidateQueries({ queryKey: facetsQuery("w", "a").queryKey }));
    await waitFor(() => expect(m.facets.mock.calls.length).toBeGreaterThan(facetCalls));
    await act(() => new Promise((r) => setTimeout(r, 20)));
    expect(m.experimentsColumns).toHaveBeenCalledTimes(1);
    expect(paramGroupCalls()).toBe(1);

    // New runs under the filters: every shown param is counted again.
    m.facets.mockResolvedValue(facets(41));
    await act(() => client.invalidateQueries({ queryKey: facetsQuery("w", "a").queryKey }));
    await waitFor(() => expect(m.experimentsColumns).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(paramGroupCalls()).toBe(2));
  });
});
