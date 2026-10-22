/** A reload paints the board from the persisted index answers before any
 *  request answers, then revalidates them in the background. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";

vi.mock("../../../api", () => ({
  api: {
    experiments: vi.fn(), experimentsPaged: vi.fn(), experimentsColumns: vi.fn(),
    experimentGroups: vi.fn(), experimentGroupRows: vi.fn(),
    metricsSchema: vi.fn(), facets: vi.fn(), config: vi.fn(), experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count, estimateSize }: { count: number; estimateSize: () => number }) => ({
    getTotalSize: () => count * estimateSize(),
    scrollToIndex: () => {},
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * estimateSize(), size: estimateSize(), end: (index + 1) * estimateSize(),
      })),
  }),
}));

import { api } from "../../../api";
import { createQueryClient } from "../../../queryClient";
import { persistQueries, restoreQueries } from "../../../queryPersist";
import { facetsQuery, rowsKey } from "../../../queries";
import { jobsPage, renderExperiments, singleRow, topRow } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const never = () => new Promise<never>(() => {});
const FACETS = {
  branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {},
  total: 3, parented: 1, jobs: 1, singles: 2,
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  for (const fn of Object.values(m)) fn.mockImplementation(never);
});

/** What the last session's board left in storage. */
function lastSession() {
  const before = createQueryClient();
  const p = persistQueries(before);
  before.setQueryData(facetsQuery("test", "my-app").queryKey, FACETS);
  before.setQueryData(["metrics-schema", "test", "my-app"], {});
  before.setQueryData(rowsKey("test", "my-app", { sort: "idx", top: "jobs" }), jobsPage([topRow(1, { name: "job_a" })]));
  before.setQueryData(rowsKey("test", "my-app", { sort: "idx", top: "singles" }), jobsPage([singleRow(2, { name: "solo" })]));
  p.flush();
  p.stop();
}

describe("a reload", () => {
  it("paints the Outer runs board from storage, marked as updating, while it revalidates", async () => {
    lastSession();
    const client = createQueryClient();
    restoreQueries(client);
    renderExperiments("/ws/test/app/my-app", client);
    expect(await screen.findByRole("link", { name: "job_a" })).toBeInTheDocument();
    expect(screen.getByText("updating…")).toBeInTheDocument();
    expect(m.experimentsPaged).toHaveBeenCalled();
  });

  it("paints the Single runs board from storage", async () => {
    lastSession();
    const client = createQueryClient();
    restoreQueries(client);
    renderExperiments("/ws/test/app/my-app?kind=singles", client);
    expect(await screen.findByRole("link", { name: "solo" })).toBeInTheDocument();
    expect(screen.queryByText(/^loading/)).toBeNull();
  });
});
