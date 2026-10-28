/** Plan 28 N2: a `pivot` report panel asks the pivot endpoint for its runs
 *  (the runs query, or the pinned verstrs) and links cells to the board. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiPivot", () => ({ pivot: vi.fn() }));
vi.mock("../../components/LazyMount", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import { pivot, type Pivot } from "../../apiPivot";
import Panel from "../Panel";
import { validate } from "../panelSpec";

const PIVOT: Pivot = {
  rows: [{ key: "d1", label: "d1", n: 2, clause: 'tags.date = "d1"' }],
  cols: [{ key: "r", label: "r", n: 2, clause: 'root = "r"' }],
  cells: [[{ n: 2, value: 0.5, clause: 'tags.date = "d1" and root = "r"' }]],
  total: 2, rows_total: 1, cols_total: 1, cell: "agg", match: null, metric: "loss", agg: "median",
};

const base = { v: 1, id: "p", app: "my_app", type: "pivot", rows: "tags.date", cols: "root" };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(pivot).mockResolvedValue(PIVOT);
});

const wrap = (spec: object) => renderWithClient(<MemoryRouter><Panel ws="w" spec={spec} /></MemoryRouter>);

describe("pivot panel", () => {
  it("validates its required fields", () => {
    expect(validate({ ...base, runs: { query: "a = 1" } }).ok).toBe(true);
    const { cols: _cols, ...noCols } = base;
    expect(validate({ ...noCols, runs: { query: "a = 1" } })).toEqual({ ok: false, error: "pivot panel needs field(s): cols" });
  });

  it("pivots the runs query and links a cell to the app's board", async () => {
    wrap({ ...base, runs: { query: 'tags.kind = "trial"' }, cell: "agg", metric: "loss", agg: "median" });
    await waitFor(() => expect(pivot).toHaveBeenCalledWith("w", "my_app", {
      rows: "tags.date", cols: "root", cell: "agg", metric: "loss", agg: "median", q: 'tags.kind = "trial"',
    }));
    const link = await screen.findByRole("link", { name: /median loss 0.5/ });
    expect(link).toHaveAttribute("href",
      `/ws/w/app/my_app?${new URLSearchParams({ q: '(tags.kind = "trial") and tags.date = "d1" and root = "r"' })}`);
  });

  it("pivots pinned runs and a scope, linking into the outer run's Runs tab", async () => {
    wrap({ ...base, runs: { verstrs: ["a", "b"] }, scope: "0.1-dev.j" });
    await waitFor(() => expect(pivot).toHaveBeenCalledWith("w", "my_app", {
      rows: "tags.date", cols: "root", cell: "count", q: 'verstr in ("a", "b")', scope: "0.1-dev.j",
    }));
    const link = await screen.findByRole("link", { name: "d1" });
    expect(link.getAttribute("href")).toMatch(/^\/ws\/w\/app\/my_app\/run\/0\.1-dev\.j\?tab=runs&q=/);
  });
});
