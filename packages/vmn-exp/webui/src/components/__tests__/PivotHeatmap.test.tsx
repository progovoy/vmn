/** Plan 28 N2: the pivot heatmap renders the server's grid as a table whose
 *  headers and cells link to the runs behind them, with a scale legend. */
import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { Pivot } from "../../apiPivot";
import PivotHeatmap from "../PivotHeatmap";

const PIVOT: Pivot = {
  rows: [{ key: "d1", label: "d1", n: 3, clause: 'tags.date = "d1"' },
    { key: "∅", label: "(none)", n: 1, clause: "tags.date = null" }],
  cols: [{ key: "g1", label: "g1", n: 3, clause: 'tags.group = "g1"' },
    { key: "g2", label: "g2", n: 1, clause: 'tags.group = "g2"' }],
  cells: [[{ n: 2, value: 0.5, hits: 1, clause: 'tags.date = "d1" and tags.group = "g1"' },
    { n: 1, value: 0, hits: 0, clause: 'tags.date = "d1" and tags.group = "g2"' }],
  [{ n: 1, value: 1, hits: 1, clause: 'tags.date = null and tags.group = "g1"' }, null]],
  total: 4, rows_total: 2, cols_total: 2, cell: "share", match: 'tags.health = "unstable"',
  metric: null, agg: null,
};

const hrefOf = (q: string) => `/runs?q=${encodeURIComponent(q)}`;

function renderHeatmap(pivot = PIVOT, baseQuery?: string) {
  return render(
    <MemoryRouter>
      <PivotHeatmap pivot={pivot} rowsField="tags.date" colsField="tags.group" hrefOf={hrefOf} baseQuery={baseQuery} />
    </MemoryRouter>,
  );
}

describe("PivotHeatmap", () => {
  it("lays the grid out as a table named for what it shows", () => {
    renderHeatmap();
    const table = screen.getByRole("table", { name: /share matching tags.health = "unstable" by tags.date × tags.group/ });
    expect(within(table).getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["tags.date \\ tags.group", "g1", "g2"]);
    expect(within(table).getAllByRole("rowheader").map((th) => th.textContent)).toEqual(["d1", "(none)"]);
    expect(within(table).getAllByRole("cell").map((td) => td.textContent)).toEqual(["50%", "0%", "100%", ""]);
  });

  it("links a share cell to its matching runs, a header to its value's runs", () => {
    renderHeatmap();
    const cell = screen.getByRole("link", { name: /tags.date d1, tags.group g1: 50% match/ });
    expect(cell).toHaveAttribute("href", hrefOf('tags.date = "d1" and tags.group = "g1" and (tags.health = "unstable")'));
    expect(screen.getByRole("link", { name: "g2" })).toHaveAttribute("href", hrefOf('tags.group = "g2"'));
    expect(screen.getByRole("link", { name: "(none)" })).toHaveAttribute("href", hrefOf("tags.date = null"));
  });

  it("keeps the base query in every link", () => {
    renderHeatmap(PIVOT, "depth > 1");
    expect(screen.getByRole("link", { name: "g2" })).toHaveAttribute("href", hrefOf('(depth > 1) and tags.group = "g2"'));
  });

  it("shows a scale legend from low to high", () => {
    renderHeatmap();
    const legend = screen.getByRole("img", { name: "Scale: 0% to 100%" });
    expect(legend).toHaveTextContent("0%");
    expect(legend).toHaveTextContent("100%");
  });

  it("says which values were left out, and when no run is in it", () => {
    renderHeatmap({ ...PIVOT, rows_total: 260, cols_total: 70 });
    expect(screen.getByText(/the 2 most common of 260 tags.date values and 2 of 70 tags.group values/)).toBeInTheDocument();
    renderHeatmap({ ...PIVOT, rows: [], cols: [], cells: [], total: 0 });
    expect(screen.getByText("No runs to pivot.")).toBeInTheDocument();
  });
});
