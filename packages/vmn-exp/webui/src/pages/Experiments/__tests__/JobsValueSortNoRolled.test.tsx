/** Plan 32: once the page answers with rows that carry no `rolled`, the
 *  value column's direction still follows only the aggregate's own metric
 *  (the URL's `job_agg_metric`, from the schema), never the main metric's
 *  goal: the server orders `job:value` by the aggregate. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

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
import { jobsPage, notFound, renderExperiments, topRow, urlParams } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const header = () => document.querySelector('th[data-col-id="value"]') as HTMLElement | null;
const sortButton = () => screen.findByRole("button", { name: /sort by value/i });
const render = async (search: string) => {
  renderExperiments(`/ws/test/app/my-app?${search}`);
  await screen.findByRole("link", { name: "grid" });
  await waitFor(() => expect(m.metricsSchema).toHaveBeenCalled());
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ val_loss: { goal: "min" }, acc: { goal: "max" } });
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  // The main metric (val_loss) goes down; the rows carry no `rolled`.
  m.experimentsPaged.mockResolvedValue(jobsPage([topRow(36, { name: "grid" })]));
});

describe("job:value on rows without rolled", () => {
  it("follows the URL's job_agg_metric goal, not the main metric's", async () => {
    await render("sort=job:value&job_agg_metric=acc");
    await waitFor(() => expect(header()).toHaveAttribute("aria-sort", "descending"));
  });

  it("shows no direction and writes none without job_agg_metric", async () => {
    await render("sort=job:value");
    fireEvent.click(await sortButton());
    expect((await sortButton()).textContent).not.toMatch(/[▴▾]/);
    expect(["ascending", "descending"]).not.toContain(header()!.getAttribute("aria-sort"));
    expect(urlParams().get("order")).toBeNull();
  });
});
