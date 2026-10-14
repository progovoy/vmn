/** Plan 23 W3: the job's facet sidebar. A param with many numeric values is
 *  a mini histogram of value buckets; a bucket adds its range as tokens. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", async (orig) => {
  const actual = await orig<typeof import("../../api")>();
  return { ...actual, api: { facets: vi.fn(), experimentGroups: vi.fn(), experimentsColumns: vi.fn() } };
});

import { api } from "../../api";
import { NONE_GROUP, type GroupOpts } from "../../apiGroups";
import { NARROW_QUERY } from "../../hooks/useMediaQuery";
import { dropFakeMedia, fakeMedia } from "../../hooks/__tests__/fakeMedia";
import FacetSidebar from "../FacetSidebar";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const group = (key: string, total: number) => ({
  key, label: key, target: null, loose: false, aggregates: {}, rows: [], rows_total: total, rows_unfiltered: total,
  counts: { total, running: 0, waiting: 0, done: total, failed: 0, stuck: 0 },
});

afterEach(dropFakeMedia);

beforeEach(() => {
  vi.clearAllMocks();
  m.facets.mockResolvedValue({
    branches: [], metric_keys: [], param_keys: ["seed", "same"], tag_keys: [],
    param_values: { seed: 40, same: 1 }, parented: 0, total: 40,
  });
  m.experimentGroups.mockImplementation((_w: string, _a: string, o: GroupOpts) => Promise.resolve({
    groups: o.group === "status" ? [group("succeeded", 40)] : [group("1", 1), group("2", 1)],
    total_groups: o.group === "status" ? 1 : 40, total_rows: 40, aggregate: "mean", running: 0,
  }));
  m.experimentsColumns.mockResolvedValue({
    verstrs: [], idx: [], total: 40,
    columns: { "params.seed": Array.from({ length: 40 }, (_, i) => i) },
  });
});

describe("FacetSidebar", () => {
  it("draws a many-valued numeric param as buckets that add a range filter", async () => {
    const onAdd = vi.fn();
    renderWithClient(<FacetSidebar ws="w" app="a" scope="J" query="x = 1" status="" onAdd={onAdd} />);
    const hist = await screen.findByRole("group", { name: "params.seed histogram" });
    expect(m.experimentsColumns).toHaveBeenCalledWith("w", "a", ["params.seed"], { scope: "J", query: "x = 1" });
    const bars = within(hist).getAllByRole("button");
    expect(bars).toHaveLength(12);
    fireEvent.click(bars[0]);
    expect(onAdd).toHaveBeenCalledWith(["params.seed >= 0", "params.seed < 3.25"]);
  });

  it("bins a continuous param sent as numeric strings, the runs without it aside", async () => {
    m.experimentsColumns.mockResolvedValue({
      verstrs: [], idx: [], total: 41,
      columns: { "params.seed": [null, ...Array.from({ length: 40 }, (_, i) => String(i / 100 + 0.006))] },
    });
    renderWithClient(<FacetSidebar ws="w" app="a" scope="J" query="" status="" onAdd={() => {}} />);
    const hist = await screen.findByRole("group", { name: "params.seed histogram" });
    expect(within(hist).getAllByRole("button")).toHaveLength(12);
  });

  it("bins a grouped numeric param whose groups include the no-value one", async () => {
    m.facets.mockResolvedValue({
      branches: [], metric_keys: [], param_keys: ["seed"], tag_keys: [],
      param_values: { seed: 20 }, parented: 0, total: 41,
    });
    m.experimentGroups.mockImplementation((_w: string, _a: string, o: GroupOpts) => Promise.resolve({
      groups: o.group === "status" ? [group("succeeded", 41)]
        : [group("0.006", 3), group(NONE_GROUP, 1), ...Array.from({ length: 18 }, (_, i) => group(String(i / 10), 2))],
      total_groups: o.group === "status" ? 1 : 30, total_rows: 41, aggregate: "mean", running: 0,
    }));
    m.experimentsColumns.mockResolvedValue({
      verstrs: [], idx: [], total: 41,
      columns: { "params.seed": [null, ...Array.from({ length: 40 }, (_, i) => i / 10)] },
    });
    renderWithClient(<FacetSidebar ws="w" app="a" scope="J" query="" status="" onAdd={() => {}} />);
    await screen.findByRole("group", { name: "params.seed histogram" });
  });

  it("never groups a param with more values than it lists (a costly grouping on a big job)", async () => {
    renderWithClient(<FacetSidebar ws="w" app="a" scope="J" query="" status="" onAdd={() => {}} />);
    await screen.findByRole("group", { name: "params.seed histogram" });
    const grouped = m.experimentGroups.mock.calls.map((c) => (c[2] as GroupOpts).group);
    expect(grouped).not.toContain("params.seed");
  });

  it("counts a many-valued param's text values from its column", async () => {
    m.experimentsColumns.mockResolvedValue({
      verstrs: [], idx: [], total: 40,
      columns: { "params.seed": Array.from({ length: 40 }, (_, i) => (i < 30 ? "adam" : `opt${i}`)) },
    });
    renderWithClient(<FacetSidebar ws="w" app="a" scope="J" query="" status="" onAdd={() => {}} />);
    const list = await screen.findByRole("list", { name: "params.seed values" });
    expect(within(list).getAllByRole("button")[0]).toHaveAccessibleName('params.seed = "adam" (30 runs)');
  });

  it("leaves out a param with one value", async () => {
    renderWithClient(<FacetSidebar ws="w" app="a" scope="J" query="" status="" onAdd={() => {}} />);
    await screen.findByRole("group", { name: "params.seed histogram" });
    expect(screen.queryByText("params.same")).toBeNull();
  });

  it("counts a many-valued param's distinct values when they aren't numbers to bin", async () => {
    m.experimentsColumns.mockResolvedValue({
      verstrs: [], idx: [], total: 40, columns: { "params.seed": Array.from({ length: 40 }, (_, i) => `${i}e999`) },
    });
    renderWithClient(<FacetSidebar ws="w" app="a" scope="J" query="" status="" onAdd={() => {}} />);
    const facet = await screen.findByRole("region", { name: "params.seed" });
    await waitFor(() => expect(facet).toHaveTextContent("40 distinct values"));
    expect(facet.querySelector(".facet-loading")).toBeNull();
  });

  it("says so instead of a placeholder when a param's counts fail", async () => {
    m.experimentGroups.mockImplementation((_w: string, _a: string, o: GroupOpts) => (o.group === "status"
      ? Promise.resolve({ groups: [group("succeeded", 40)], total_groups: 1, total_rows: 40, aggregate: "mean", running: 0 })
      : Promise.reject(new Error("boom"))));
    m.experimentsColumns.mockRejectedValue(new Error("boom"));
    renderWithClient(<FacetSidebar ws="w" app="a" scope="J" query="" status="" onAdd={() => {}} />);
    const facet = await screen.findByRole("region", { name: "params.seed" });
    await waitFor(() => expect(facet).toHaveTextContent("Couldn't count its values"), { timeout: 4000 });
    expect(facet.querySelector(".facet-loading")).toBeNull();
  });

  it("is a drawer behind a Filters button on a phone", async () => {
    fakeMedia([NARROW_QUERY]);
    renderWithClient(<FacetSidebar ws="w" app="a" scope="J" query="" status="" onAdd={() => {}} />);
    const toggle = screen.getByRole("button", { name: "Facets" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("complementary", { name: "Facets" })).toBeNull();
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByRole("complementary", { name: "Facets" })).toBeInTheDocument());
  });
});
