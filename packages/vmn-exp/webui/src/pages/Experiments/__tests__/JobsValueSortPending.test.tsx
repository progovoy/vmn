/** Plan 31 §2 / plan 32: until the first page answers (no `rolled` yet) the
 *  value column's direction follows the goal of the metric the server orders
 *  `job:value` by, the URL's `job_agg_metric`, from the metrics schema; with
 *  no known goal it shows no direction and a click writes none. */
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

import { api } from "../../../api";
import { notFound, renderExperiments, urlParams } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const header = () => document.querySelector('th[data-col-id="value"]') as HTMLElement | null;
const sortButton = () => screen.findByRole("button", { name: /sort by value/i });
const render = (search: string) => renderExperiments(`/ws/test/app/my-app?${search}`);
const noDirection = async () => {
  expect((await sortButton()).textContent).not.toMatch(/[▴▾]/);
  expect(["ascending", "descending"]).not.toContain(header()!.getAttribute("aria-sort"));
};
const schemaLoaded = () => waitFor(() => expect(m.metricsSchema).toHaveBeenCalled());

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ val_loss: { goal: "min" }, acc: { goal: "max" } });
  m.facets.mockResolvedValue({
    branches: [], metric_keys: ["acc", "val_loss"], param_keys: [], tag_keys: [],
    param_values: {}, parented: 1, total: 9, jobs: 1, singles: 0,
  });
  m.config.mockRejectedValue(notFound());
  // The page never answers: no `rolled`, no `main`.
  m.experimentsPaged.mockReturnValue(new Promise(() => {}));
});

describe("job:value before the first page answers", () => {
  it("follows the URL's job_agg_metric goal, not the main metric's", async () => {
    render("sort=job:value&job_agg_metric=acc");
    await waitFor(() => expect(header()).toHaveAttribute("aria-sort", "descending"));
    expect((await sortButton()).textContent).toMatch(/▾$/);
    fireEvent.click(await sortButton());
    await waitFor(() => expect(urlParams().get("order")).toBe("asc"));
  });

  it("shows no direction and writes none without a known goal (the app's aggregate)", async () => {
    render("sort=job:value");
    await schemaLoaded();
    fireEvent.click(await sortButton());
    await noDirection();
    expect(urlParams().get("order")).toBeNull();
  });

  it("shows no direction for a job_agg_metric the schema has no entry for", async () => {
    render("sort=job:value&job_agg_metric=f1");
    await schemaLoaded();
    fireEvent.click(await sortButton());
    await noDirection();
    expect(urlParams().get("order")).toBeNull();
  });
});
