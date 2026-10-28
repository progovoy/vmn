/** Plan 28 N6 follow-up: the tree asks for every page under the filters it
 *  is given (the Runs tab's), and asks again when they change. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../../../apiTree", async (orig) => ({
  ...(await orig<typeof import("../../../apiTree")>()),
  fetchChildren: vi.fn(),
}));
vi.mock("../../../api", () => ({ api: { metricsSchema: vi.fn() } }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 40,
    scrollToIndex: () => {},
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * 40, size: 40, end: (index + 1) * 40 })),
  }),
}));

import { api } from "../../../api";
import { fetchChildren, type TreeFilter, type TreeRow } from "../../../apiTree";
import { job } from "../../../util/__tests__/jobFixture";
import JobTree from "../JobTree";

const LAUNCH = "1.0.0-dev.launch";
const fetched = fetchChildren as unknown as ReturnType<typeof vi.fn>;
const D1 = {
  idx: 1, verstr: "1.0.0-dev.d1", name: "d1", code_verstr: "1.0.0", timestamp: null, note: null,
  branch: null, base_version: null, metrics: {}, status: "succeeded", tree_status: "failed",
  job: job({}), children: ["x"], kind: "outer", open: true, matched: 2,
} as unknown as TreeRow;

function Switched({ first, then }: { first: TreeFilter; then: TreeFilter }) {
  const [filter, setFilter] = useState(first);
  return (
    <>
      <button type="button" onClick={() => setFilter(then)}>switch</button>
      <JobTree ws="test" app="my-app" verstr={LAUNCH} filter={filter} />
    </>
  );
}

function renderTree(first: TreeFilter, then: TreeFilter = first) {
  return renderWithClient(<MemoryRouter><Switched first={first} then={then} /></MemoryRouter>);
}

const filtersAsked = () => fetched.mock.calls.map((c) => [c[2], c[3]?.filter]);

beforeEach(() => {
  vi.clearAllMocks();
  (api.metricsSchema as ReturnType<typeof vi.fn>).mockResolvedValue({});
  fetched.mockImplementation(async (_ws: string, _app: string, parent: string) =>
    ({ rows: parent === LAUNCH ? [D1] : [], total: parent === LAUNCH ? 1 : 0, next_cursor: null }));
});

describe("a filtered tree", () => {
  it("asks for every level's children under the filters", async () => {
    const filter = { status: "failed", query: 'tags.kind = "date"' };
    renderTree(filter);
    await screen.findByRole("link", { name: "d1" });
    await waitFor(() => expect(filtersAsked()).toEqual([[LAUNCH, filter], [D1.verstr, filter]]));
  });

  it("asks again when the filters change", async () => {
    const next = { status: "running" };
    renderTree({ status: "failed" }, next);
    await screen.findByRole("link", { name: "d1" });
    fetched.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "switch" }));
    await waitFor(() => expect(filtersAsked()).toContainEqual([LAUNCH, next]));
  });
});
