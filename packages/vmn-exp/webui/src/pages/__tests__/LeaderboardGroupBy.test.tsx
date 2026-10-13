import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    config: vi.fn(),
    experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));

import { api } from "../../api";
import { listViews } from "../../util/savedViews";
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const facets = (extra = {}) => ({
  branches: ["main"], metric_keys: ["loss"], param_keys: ["lr", "seed"], tag_keys: ["team"],
  param_values: { lr: 3, seed: 40 }, parented: 0, total: 2, ...extra,
});
const groupBy = () => screen.findByRole("button", { name: /^group by/i });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.experiments.mockResolvedValue(page([row(1), row(2)]));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.config.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.facets.mockResolvedValue(facets());
});

describe("the board's Group by control (plan 22 W1)", () => {
  it("sits next to Columns and defaults to the parent run when runs have a parent", async () => {
    m.facets.mockResolvedValue(facets({ parented: 1 }));
    renderBoard();
    await waitFor(async () => expect(await groupBy()).toHaveTextContent("Group by: parent run"));
    const actions = (await groupBy()).closest(".board-actions")!;
    expect(within(actions as HTMLElement).getByRole("button", { name: /^columns/i })).toBeInTheDocument();
    expect(urlParams().has("group")).toBe(false);
  });

  it("is ungrouped for an app without parented runs, and hides a param with > 20 values", async () => {
    renderBoard();
    fireEvent.click(await groupBy());
    expect(await groupBy()).toHaveTextContent(/^Group by ▾$/);
    expect(screen.getByRole("menuitemradio", { name: "none" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("menuitemradio", { name: "params.lr" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitemradio", { name: "params.seed" })).toBeNull();
  });

  it("writes the pick and the aggregate into the URL, and a saved view keeps them", async () => {
    renderBoard();
    fireEvent.click(await groupBy());
    fireEvent.click(screen.getByRole("menuitemradio", { name: "tags.team" }));
    await waitFor(() => expect(urlParams().get("group")).toBe("tags.team"));
    fireEvent.click(await groupBy());
    fireEvent.click(within(screen.getByRole("group", { name: "Aggregate" })).getByRole("button", { name: "median" }));
    await waitFor(() => expect(urlParams().get("agg")).toBe("median"));

    fireEvent.click(screen.getByRole("button", { name: /^views/i }));
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "by team" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const saved = new URLSearchParams(listViews("test", "my-app")[0].search);
    expect(saved.get("group")).toBe("tags.team");
    expect(saved.get("agg")).toBe("median");
  });

  it("opens a saved grouped view as it was saved", async () => {
    renderBoard("/ws/test/app/my-app?group=branch&agg=best");
    expect(await groupBy()).toHaveTextContent("Group by: branch");
    fireEvent.click(await groupBy());
    expect(within(screen.getByRole("group", { name: "Aggregate" })).getByRole("button", { name: "best" }))
      .toHaveAttribute("aria-pressed", "true");
  });
});
