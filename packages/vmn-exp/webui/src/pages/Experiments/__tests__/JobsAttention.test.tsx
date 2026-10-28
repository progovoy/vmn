/** Plan 28 P1 on the Outer runs view: the app's attention strip (its parts
 *  open All runs filtered), each outer run's attention counts as chips, and
 *  the `job:attention` sort. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../../api", () => ({
  api: {
    experiments: vi.fn(), experimentsPaged: vi.fn(), experimentsColumns: vi.fn(),
    experimentGroups: vi.fn(), experimentGroupRows: vi.fn(),
    metricsSchema: vi.fn(), facets: vi.fn(), config: vi.fn(), experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
const appStatus = vi.hoisted(() => vi.fn());
vi.mock("../../../apiShell", () => ({ apiShell: { appStatus: () => appStatus() } }));
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
import { job } from "../../../util/__tests__/jobFixture";
import { jobsPage, notFound, renderExperiments, topRow, urlParams } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const GRID = topRow(36, { name: "grid", job: job({ attention: { unstable: 2, nonfinite: 0 } }) });
const CALM = topRow(35, { name: "calm", job: job({ attention: { unstable: 0, nonfinite: 0 } }) });
const STATUS = {
  total: 40, failed_recent: 0, rollup: "stuck",
  counts: { created: 0, running: 3, stuck: 1, succeeded: 36, failed: 0 },
  attention: [
    { key: "unstable", label: "unstable", level: "warn", count: 2, q: 'tags.health = "unstable"' },
    { key: "nonfinite", label: "nonfinite", level: "error", count: 0, q: 'tags.state = "nonfinite"' },
  ],
};
const nameCell = (name: string) => screen.getByRole("link", { name }).closest("tr")!.querySelector('[data-col-id="name"]')! as HTMLElement;
const linkParams = (name: string) =>
  new URLSearchParams(screen.getByRole("link", { name }).getAttribute("href")!.split("?")[1]);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ val_loss: { goal: "min" } });
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  m.experimentsPaged.mockResolvedValue(jobsPage([GRID, CALM]));
  appStatus.mockResolvedValue(STATUS);
});

describe("the attention strip on the Outer runs view", () => {
  it("shows the app's status, its parts opening All runs filtered", async () => {
    renderExperiments("/ws/test/app/my-app?sort=job%3Atotal&kind=jobs&density=compact");
    const strip = (await screen.findByRole("link", { name: "1 stuck" })).closest('[role="status"]')!;
    expect(strip).toHaveTextContent("1 stuck · 2 unstable · 3 running");
    const unstable = linkParams("2 unstable");
    expect(unstable.get("view")).toBe("all");
    expect(unstable.get("q")).toBe('tags.health = "unstable"');
    expect(unstable.get("density")).toBe("compact");
    for (const k of ["sort", "kind"]) expect(unstable.has(k)).toBe(false);
    expect(linkParams("1 stuck").get("status")).toBe("stuck");
    expect(linkParams("1 stuck").get("view")).toBe("all");
  });
});

describe("an outer run's attention counts", () => {
  it("show as level-coloured chips beside its name, zero ones left out", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "grid" });
    await waitFor(() => expect(within(nameCell("grid")).getByText("2 unstable")).toHaveClass("attention-warn"));
    expect(within(nameCell("grid")).queryByText(/nonfinite/)).toBeNull();
    expect(nameCell("calm").querySelector(".job-attention")).toBeNull();
  });
});

describe("the needs-attention sort", () => {
  it("sorts by job:attention, the worst first", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "grid" });
    fireEvent.click(screen.getByRole("button", { name: /sort by needs attention/i }));
    await waitFor(() => expect(urlParams().get("sort")).toBe("job:attention"));
    expect(urlParams().get("order")).toBe("desc");
    await waitFor(() => expect(m.experimentsPaged.mock.calls.slice(-1)[0][2])
      .toEqual(expect.objectContaining({ sort: "job:attention", order: "desc" })));
  });
});
