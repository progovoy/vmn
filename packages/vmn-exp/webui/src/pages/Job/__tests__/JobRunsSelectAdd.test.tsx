/** "Select all N matching" on a job's Runs tab adds the job's query to the
 *  app-wide selection: picks from other jobs stay, the loaded runs are
 *  absorbed, and unticking one of them turns the query back into picks. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../../../api", async (orig) => {
  const actual = await orig<typeof import("../../../api")>();
  return {
    ...actual,
    api: {
      experiment: vi.fn(), experiments: vi.fn(), experimentsPaged: vi.fn(), experimentGroups: vi.fn(),
      experimentGroupRows: vi.fn(), experimentsColumns: vi.fn(), facets: vi.fn(), metricsSchema: vi.fn(),
      action: vi.fn(), actionPreview: vi.fn(), job: vi.fn(),
    },
  };
});
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 48, size: 48, end: (index + 1) * 48,
      })),
  }),
}));

import { api } from "../../../api";
import type { ExperimentRow } from "../../../types";
import { readPicks, writePicks } from "../../../util/runSelection";
import { readGroups } from "../../../util/selectionGroups";
import SelectionTrayHost from "../../SelectionTrayHost";
import JobRuns from "../JobRuns";

const JOB = "0.0.2-rc.1";
const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const row = (i: number): ExperimentRow => ({
  idx: i, verstr: `0.0.2-dev.t${i}`, code_verstr: "0.0.2", timestamp: "2026-10-14T10:00:00Z", note: null,
  branch: "main", base_version: "0.0.1", params: {}, metrics: { loss: i / 10 },
  status: "failed", depth: 1, parent: JOB, root: JOB,
} as ExperimentRow);

function renderRuns() {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${JOB}?tab=runs&status=failed`]}>
      <SelectionTrayHost ws="test" app="my-app">
        <Routes>
          <Route
            path="/ws/:ws/app/:app/run/:verstr"
            element={<JobRuns ws="test" app="my-app" verstr={JOB} name="hist-0012" paused={false} onPaused={() => {}} />}
          />
        </Routes>
      </SelectionTrayHost>
    </MemoryRouter>,
  );
}

const tray = () => screen.getByRole("region", { name: "Selection" });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  m.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
  m.experimentsPaged.mockResolvedValue({ rows: [row(1), row(2)], total: 4000 });
  m.facets.mockResolvedValue({
    branches: ["main"], metric_keys: ["loss"], param_keys: [], tag_keys: [], param_values: {},
    parented: 4000, total: 4000,
  });
  m.experimentsColumns.mockResolvedValue({ verstrs: [], idx: [], columns: {}, total: 0 });
  m.experimentGroups.mockRejectedValue(new Error("no groups"));
  writePicks("test", "my-app", [{ verstr: "other", job: "J2", name: "other" }]);
});

async function selectAllMatching() {
  await screen.findByText("0.0.2-dev.t1");
  fireEvent.click(screen.getByRole("checkbox", { name: `Select 0.0.2-dev.t1` }));
  fireEvent.click(await screen.findByRole("button", { name: "Select all 4,000 matching" }));
}

describe("select all matching on a job's Runs tab", () => {
  it("adds the query to the selection: picks of other jobs stay", async () => {
    renderRuns();
    await selectAllMatching();
    await waitFor(() => expect(within(tray()).getByRole("status")).toHaveTextContent("4,001 selected from 2 outer runs"));
    expect(readPicks("test", "my-app").map((p) => p.verstr)).toEqual(["other"]);
    expect(readGroups("test", "my-app")).toEqual([expect.objectContaining({
      scope: JOB, q: "", status: "failed", count: 4000, job: JOB, label: "hist-0012",
    })]);
    expect(screen.getByRole("checkbox", { name: "Select 0.0.2-dev.t2" })).toBeChecked();
    expect(within(tray()).queryByRole("button", { name: /select all/i })).toBeNull();
  });

  it("turns the query back into the loaded runs minus one when that one is unticked", async () => {
    renderRuns();
    await selectAllMatching();
    await waitFor(() => expect(readGroups("test", "my-app")).toHaveLength(1));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select 0.0.2-dev.t1" }));
    expect(readGroups("test", "my-app")).toEqual([]);
    expect(readPicks("test", "my-app").map((p) => p.verstr)).toEqual(["other", "0.0.2-dev.t2"]);
  });

  it("archives the query and the other picks, refreshing the board", async () => {
    m.actionPreview.mockResolvedValue({ count: 4000, sample: [] });
    m.action.mockResolvedValue({ id: "j1", command: [], status: "running", exit_code: null, log: "" });
    renderRuns();
    await selectAllMatching();
    fireEvent.click(within(tray()).getByRole("button", { name: "Archive" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Archive 4,001 runs?");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(m.action).toHaveBeenCalledWith("test", "my-app", "exp_archive",
      { scope: JOB, status: "failed" }));
  });
});
