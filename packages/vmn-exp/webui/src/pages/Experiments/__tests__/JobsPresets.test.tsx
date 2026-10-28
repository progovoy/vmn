/** Plan 28 §4.5: the Live and Review presets of the Outer runs view,
 *  `view=live|review` beside Outer runs | Single runs | All runs. Live =
 *  the outer runs in flight or ended within LIVE_WINDOW, needs attention
 *  first, followed live; Review = the ended ones, newest first, each with
 *  its baseline chip. The preset travels as `top_q`, so a search still
 *  matches every run of a tree. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../../api", () => ({
  api: {
    experiments: vi.fn(), experimentsPaged: vi.fn(), experimentsColumns: vi.fn(),
    experimentGroups: vi.fn(), experimentGroupRows: vi.fn(),
    metricsSchema: vi.fn(), facets: vi.fn(), config: vi.fn(), experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../../apiBaseline", () => ({ baselineChips: vi.fn() }));
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
import { baselineChips } from "../../../apiBaseline";
import { FakeSource, lastSource } from "../../../hooks/__tests__/fakeEventSource";
import { CHIP, REF } from "../../../components/__tests__/baselineFixture";
import { VIEW_KEY } from "../experimentsView";
import { LIVE_QUERY, LIVE_WINDOW, REVIEW_QUERY } from "../presets";
import { jobsPage, renderExperiments, topRow, urlParams } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const FACETS = { branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {}, total: 99_600 };
const WITH_JOBS = { ...FACETS, parented: 80_000, jobs: 20, singles: 19_580 };
const LAUNCH = topRow(36, { name: "launch" });
const views = () => screen.getByRole("group", { name: "Experiments view" });
const presets = () => screen.getByRole("group", { name: "Outer runs preset" });
const pressed = (group: HTMLElement, name: RegExp) => within(group).getByRole("button", { name }).getAttribute("aria-pressed");
const lastOpts = () => m.experimentsPaged.mock.calls.slice(-1)[0][2];

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  FakeSource.instances = [];
  vi.stubGlobal("EventSource", FakeSource);
  m.metricsSchema.mockResolvedValue({});
  m.config.mockRejectedValue(new Error("nf"));
  m.facets.mockResolvedValue(WITH_JOBS);
  m.experimentsPaged.mockResolvedValue(jobsPage([LAUNCH], 1));
  vi.mocked(baselineChips).mockResolvedValue({ [LAUNCH.verstr]: { ...CHIP, baseline: REF } });
});
afterEach(() => vi.unstubAllGlobals());

describe("the presets", () => {
  it("are a switch beside the views, the views' options unchanged", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "launch" });
    expect(within(presets()).getAllByRole("button").map((b) => b.textContent)).toEqual(["Live", "Review"]);
    expect(within(views()).getAllByRole("button").map((b) => b.textContent))
      .toEqual(["Outer runs (20)", "Single runs (19,580)", "All runs"]);
    expect(pressed(presets(), /^Live/)).toBe("false");
    expect(lastOpts().topQuery).toBeUndefined();
  });

  it("Live is the outer runs in flight or ended within the window, needs attention first", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "launch" });
    fireEvent.click(within(presets()).getByRole("button", { name: "Live" }));
    await waitFor(() => expect(lastOpts()).toEqual(expect.objectContaining({
      top: "jobs", topQuery: LIVE_QUERY, sort: "job:attention",
    })));
    expect(LIVE_QUERY).toContain(`finished_at >= ago("${LIVE_WINDOW}")`);
    expect(LIVE_QUERY).toContain('tree_status in ("running", "created", "stuck")');
    expect(urlParams().get("view")).toBe("live");
    expect(pressed(presets(), /^Live/)).toBe("true");
    expect(pressed(views(), /^Outer runs/)).toBe("true");
    expect(localStorage.getItem(`${VIEW_KEY}:test/my-app`)).toBe("live");
  });

  it("Live follows the top-level scope's events", async () => {
    renderExperiments("/ws/test/app/my-app?view=live");
    await screen.findByRole("link", { name: "launch" });
    expect(lastSource().url).toBe("/api/v1/workspaces/test/apps/my-app/events?scope=top");
  });

  it("Review is the ended outer runs, newest first, each with its baseline chip", async () => {
    renderExperiments("/ws/test/app/my-app?view=review");
    await screen.findByRole("link", { name: "launch" });
    expect(lastOpts()).toEqual(expect.objectContaining({ top: "jobs", topQuery: REVIEW_QUERY, sort: "idx" }));
    expect(pressed(presets(), /^Review/)).toBe("true");
    expect(await screen.findByText(/▼ best_value from 2024-12/)).toBeInTheDocument();
  });

  it("is remembered for the app", async () => {
    localStorage.setItem(`${VIEW_KEY}:test/my-app`, "review");
    renderExperiments();
    await screen.findByRole("link", { name: "launch" });
    expect(lastOpts()).toEqual(expect.objectContaining({ topQuery: REVIEW_QUERY }));
  });

  it("a sort in the URL beats the preset's", async () => {
    renderExperiments("/ws/test/app/my-app?view=live&sort=job:progress");
    await screen.findByRole("link", { name: "launch" });
    expect(lastOpts()).toEqual(expect.objectContaining({ topQuery: LIVE_QUERY, sort: "job:progress" }));
  });

  it("keeps a search over every run of a tree beside the preset", async () => {
    renderExperiments("/ws/test/app/my-app?view=live&q=metrics.loss%20%3C%201");
    await screen.findByRole("link", { name: "launch" });
    expect(lastOpts()).toEqual(expect.objectContaining({
      query: "metrics.loss < 1", matchSubtree: true, topQuery: LIVE_QUERY,
    }));
  });

  it("Outer runs leaves the preset, the filters kept", async () => {
    renderExperiments("/ws/test/app/my-app?view=live&status=failed");
    await screen.findByRole("link", { name: "launch" });
    fireEvent.click(within(views()).getByRole("button", { name: /^Outer runs/ }));
    await waitFor(() => expect(urlParams().get("view")).toBe("jobs"));
    expect(urlParams().get("status")).toBe("failed");
    await waitFor(() => expect(lastOpts().topQuery).toBeUndefined());
  });

  it("its command line selects the same outer runs", async () => {
    renderExperiments("/ws/test/app/my-app?view=review");
    await screen.findByRole("link", { name: "launch" });
    expect(screen.getByText(/vmn-exp list my\/app --query/).textContent)
      .toContain(`depth = 0 and kind = "outer" and (${REVIEW_QUERY})`);
  });
});
