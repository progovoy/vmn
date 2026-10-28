/** Plan 28 N6 follow-up: the Runs tab's tree layout keeps the tab's filter
 *  bar and hands the URL's filters (status, query, search, branch, sort)
 *  to the tree. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../JobRuns", () => ({ default: () => <div>flat board</div> }));
vi.mock("../JobTree", () => ({
  default: ({ filter }: { filter?: unknown }) => <output data-testid="tree-filter">{JSON.stringify(filter ?? null)}</output>,
}));
vi.mock("../../../shell/useShellData", () => ({ useScopedStatus: () => ({ data: undefined }) }));
vi.mock("../../../queries", async (orig) => ({
  ...(await orig<typeof import("../../../queries")>()),
  useFacets: () => ({ branches: ["main"], metric_keys: ["loss"], param_keys: [] }),
}));

import JobRunsTab from "../JobRunsTab";

const JOB = "0.0.2-rc.1";

function renderTab(search: string) {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${JOB}${search}`]}>
      <Routes>
        <Route path="/ws/:ws/app/:app/run/:verstr" element={
          <JobRunsTab ws="test" app="my-app" verstr={JOB} paused={false} onPaused={() => {}} />
        } />
      </Routes>
    </MemoryRouter>,
  );
}

const treeFilter = () => JSON.parse(screen.getByTestId("tree-filter").textContent!);

beforeEach(() => localStorage.clear());

describe("the Runs tab's tree", () => {
  it("gets the URL's filters and sort", () => {
    const q = encodeURIComponent("metrics.loss > 1");
    renderTab(`?tab=runs&layout=tree&status=failed&q=${q}&branch=main&sort=loss&order=asc&archived=1`);
    expect(treeFilter()).toEqual({
      status: "failed", query: '(metrics.loss > 1) and (branch = "main")', sort: "loss", order: "asc", archived: true,
    });
  });

  it("is unfiltered without them", () => {
    renderTab("?tab=runs&layout=tree");
    expect(treeFilter()).toEqual({});
  });

  it("keeps the filter bar above the tree", () => {
    renderTab("?tab=runs&layout=tree&status=failed");
    expect(screen.getByLabelText("Filter query")).toBeInTheDocument();
  });
});
