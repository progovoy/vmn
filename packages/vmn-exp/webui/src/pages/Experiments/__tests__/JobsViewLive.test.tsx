/** The Jobs view live (plan 23 S5, scope `top`) and on a phone (cards). */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, screen, within } from "@testing-library/react";

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
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    scrollToIndex: () => {},
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * 48, size: 48, end: (index + 1) * 48 })),
  }),
}));

import { api } from "../../../api";
import { FakeSource, lastSource } from "../../../hooks/__tests__/fakeEventSource";
import { dropFakeMedia, fakeMedia } from "../../../hooks/__tests__/fakeMedia";
import { NARROW_QUERY } from "../../../hooks/useMediaQuery";
import { job } from "../../../util/__tests__/jobFixture";
import { jobsPage, notFound, renderExperiments, singleRow, topRow } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const GRID = topRow(36, { name: "lr_layers_grid" });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  FakeSource.instances = [];
  vi.stubGlobal("EventSource", FakeSource);
  m.metricsSchema.mockResolvedValue({ val_loss: { goal: "min" } });
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  m.experimentsPaged.mockResolvedValue(jobsPage([GRID, singleRow(2, { name: "solo" })]));
});
afterEach(() => {
  vi.unstubAllGlobals();
  dropFakeMedia();
});

describe("the Jobs view, live", () => {
  it("follows the top-level scope's events and refreshes on a change", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(lastSource().url).toBe("/api/v1/workspaces/test/apps/my-app/events?scope=top");
    act(() => lastSource().open());
    const before = m.experimentsPaged.mock.calls.length;
    m.experimentsPaged.mockResolvedValue(jobsPage([
      topRow(36, { name: "lr_layers_grid", job: job({ done: 1500 }) }), singleRow(2, { name: "solo" }),
    ]));
    act(() => lastSource().emit("change", { generation: "g2", changed: { rows: 3, jobs: [GRID.verstr] } }));
    expect(await screen.findByText(/^1,500\/2,000/)).toBeInTheDocument();
    expect(m.experimentsPaged.mock.calls.length).toBeGreaterThan(before);
  });
});

describe("the Jobs view on a phone", () => {
  it("shows a card per job: name, status, progress and best", async () => {
    fakeMedia([NARROW_QUERY]);
    renderExperiments();
    const link = await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(screen.queryByRole("grid")).toBeNull();
    const card = link.closest("li")!;
    expect(card.querySelector(".job-progress-text")?.textContent).toBe("1,412/2,000 · 3 failed · 41/min · ETA 14m");
    expect(within(card).getByText(/running/i)).toBeInTheDocument();
    expect(card.textContent).toContain("0.182");
    expect(within(card).getByRole("checkbox", { name: `Select ${GRID.verstr}` })).toBeInTheDocument();
  });
});
