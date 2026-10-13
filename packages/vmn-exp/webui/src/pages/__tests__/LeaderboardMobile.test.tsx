/** Plan 20 C8: below 640px the board's rows become cards — name + status,
 *  the primary metric large, branch · when — and selection still works. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));

import { api } from "../../api";
import { NARROW_QUERY } from "../../hooks/useMediaQuery";
import { fmtVal } from "../../util";
import { dropFakeMedia, fakeMedia } from "../../hooks/__tests__/fakeMedia";
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;
const cards = (path?: string) => {
  renderBoard(path);
  return screen.findByRole("list", { name: "experiments" });
};
const card = (name: string) => screen.getByRole("link", { name }).closest("li") as HTMLElement;

const ROWS = [
  row(1, { name: "baseline", branch: "main", metrics: { loss: 0.5, acc: 0.81 }, status: "succeeded" }),
  row(2, { branch: "feat/x", metrics: { loss: 0.25, acc: 0.9 }, status: "running" }),
  row(3, {
    kind: "outer", children: [v(4)], depth: 0, parent: null, metrics: { loss: 0.4 },
    status: "created", tree_status: "succeeded",
  }),
  row(4, { kind: "inner", parent: v(3), depth: 1, metrics: { loss: 0.3 } }),
];

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  fakeMedia([NARROW_QUERY]);
  m.metricsSchema.mockResolvedValue({ loss: { goal: "min" }, acc: { goal: "max" } });
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page(ROWS));
  m.experimentsPaged.mockResolvedValue({ rows: ROWS, total: ROWS.length });
  m.experiment.mockResolvedValue({ metadata: { verstr: "x" }, metrics: {}, series: {}, patches: {} });
});
afterEach(dropFakeMedia);

describe("the leaderboard below 640px", () => {
  it("shows a card per run instead of the wide grid", async () => {
    const list = await cards();
    expect(screen.queryByRole("grid", { name: "experiments" })).toBeNull();
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
  });

  it("puts the name and the status on the first line", async () => {
    await cards();
    const head = card("baseline").querySelector(".lb-mcard-head") as HTMLElement;
    expect(within(head).getByRole("link", { name: "baseline" })).toHaveAttribute("href", `/ws/test/app/my-app/run/${v(1)}`);
    expect(within(head).getByText("succeeded")).toBeInTheDocument();
    // An unnamed run's verstr is its name.
    expect(within(card(v(2))).getByText("running")).toBeInTheDocument();
  });

  it("shows the primary metric large: the first declared goal by default", async () => {
    await cards();
    const metric = card("baseline").querySelector(".lb-mcard-metric") as HTMLElement;
    expect(metric).toHaveTextContent("loss");
    expect(metric.querySelector(".lb-mcard-value")).toHaveTextContent("0.5");
    expect(metric).not.toHaveTextContent("0.81");
  });

  it("mutes a run that never logged the metric", async () => {
    m.experiments.mockResolvedValue(page([row(1, { name: "silent", metrics: {} }), ...ROWS.slice(1)]));
    await cards();
    const value = card("silent").querySelector(".lb-mcard-value") as HTMLElement;
    expect(value).toHaveTextContent(fmtVal(null));
    expect(value).toHaveClass("missing");
    expect(card(v(2)).querySelector(".lb-mcard-value")).not.toHaveClass("missing");
  });

  it("shows the metric the board is sorted by", async () => {
    await cards("/ws/test/app/my-app?sort=acc");
    expect(card("baseline").querySelector(".lb-mcard-value")).toHaveTextContent("0.81");
    expect(card("baseline").querySelector(".lb-mcard-metric")).toHaveTextContent("acc");
  });

  it("closes with branch · when", async () => {
    await cards();
    const foot = card(v(2)).querySelector(".lb-mcard-foot") as HTMLElement;
    expect(foot).toHaveTextContent(/feat\/x · \d+m ago/);
    expect(foot).toHaveTextContent("@2");
  });

  it("heads an outer run with its tree status, and still folds its inner runs", async () => {
    await cards();
    const outer = card(v(3));
    expect(within(outer).getByText("succeeded")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: v(4) })).toBeNull();
    fireEvent.click(within(outer).getByRole("button", { name: `Expand ${v(3)}` }));
    expect(await screen.findByRole("link", { name: v(4) })).toBeInTheDocument();
  });

  it("still selects runs, one at a time and all on screen", async () => {
    await cards();
    fireEvent.click(within(card("baseline")).getByRole("checkbox", { name: `Select ${v(1)}` }));
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([v(1)]));
    expect(card("baseline")).toHaveClass("checked");
    expect(await screen.findByRole("region", { name: "Selection" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all visible runs" }));
    await waitFor(() => expect(urlParams().getAll("sel")).toHaveLength(3));
  });

  it("opens the run from anywhere on the card", async () => {
    await cards();
    fireEvent.click(card("baseline").querySelector(".lb-mcard-foot")!);
    expect(await screen.findByRole("button", { name: "go-back" })).toBeInTheDocument();
  });
});

describe("the leaderboard at 640px and up", () => {
  it("keeps the grid", async () => {
    dropFakeMedia();
    renderBoard();
    expect(await screen.findByRole("grid", { name: "experiments" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "experiments" })).toBeNull();
  });
});
