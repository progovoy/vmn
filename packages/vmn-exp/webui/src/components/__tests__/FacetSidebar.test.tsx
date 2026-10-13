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
import type { GroupOpts } from "../../apiGroups";
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

  it("leaves out a param with one value", async () => {
    renderWithClient(<FacetSidebar ws="w" app="a" scope="J" query="" status="" onAdd={() => {}} />);
    await screen.findByRole("group", { name: "params.seed histogram" });
    expect(screen.queryByText("params.same")).toBeNull();
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
