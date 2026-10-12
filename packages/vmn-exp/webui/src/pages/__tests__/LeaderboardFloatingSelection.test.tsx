import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    experiment: vi.fn(),
    action: vi.fn(),
    job: vi.fn(),
    apps: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
const appStatus = vi.hoisted(() => vi.fn());
vi.mock("../../apiShell", () => ({ apiShell: { appStatus: () => appStatus() } }));
const KNOWN_APP = {
  total: 1, counts: { created: 0, running: 0, stuck: 0, succeeded: 1, failed: 0 }, failed_recent: 0, rollup: null,
};
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 48, size: 48, end: (index + 1) * 48,
      })),
  }),
}));

import { api } from "../../api";
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;
const ALL = [1, 2, 3, 4, 5].map(v);
const checkbox = (i: number) =>
  within(screen.getByRole("link", { name: v(i) }).closest("tr")!).getByRole("checkbox");
const bar = () => screen.findByRole("region", { name: "Selection" });
const noBar = () => expect(screen.queryByRole("region", { name: "Selection" })).toBeNull();
const headerBox = () => screen.findByRole("checkbox", { name: "Select all visible runs" });

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page([1, 2, 3, 4, 5].map((i) => row(i)), 900));
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 900 });
  appStatus.mockResolvedValue(KNOWN_APP);
  m.apps.mockResolvedValue([{ name: "my/app", experiments: 900, versions: 1 }]);
});

describe("the floating selection bar", () => {
  it("is absent, and the toolbar has no selection actions, while nothing is selected", async () => {
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    noBar();
    expect(screen.queryByRole("button", { name: /select all/i })).toBeNull();
    expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
    expect(document.querySelector(".sel-bar-spacer")).toBeNull();
  });

  it("appears once a run is selected, with a count badge, the label and the actions", async () => {
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    fireEvent.click(checkbox(1));
    const sel = await bar();
    expect(sel).toHaveClass("sel-bar");
    expect(within(sel).getByText("1", { selector: ".sel-badge" })).toBeInTheDocument();
    expect(within(sel).getByText("run selected")).toBeInTheDocument();
    expect(within(sel).getByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(within(sel).getByRole("button", { name: /select all 500 matching/i })).toBeInTheDocument();
    const toolbar = document.querySelector(".toolbar") as HTMLElement;
    expect(within(toolbar).queryByRole("button", { name: "Archive" })).toBeNull();
    expect(within(toolbar).getByRole("button", { name: "New run" })).toBeInTheDocument();
  });

  it("offers the diff, the compare table and the overlay for two runs", async () => {
    renderBoard(`/ws/test/app/my-app?sel=${v(1)}&sel=${v(2)}`);
    const sel = await bar();
    expect(within(sel).getByText("2", { selector: ".sel-badge" })).toBeInTheDocument();
    expect(within(sel).getByText("runs selected")).toBeInTheDocument();
    expect(within(sel).getByRole("button", { name: /code diff of 2 selected/i })).toBeInTheDocument();
    expect(within(sel).getByRole("button", { name: /compare 2 in a table/i })).toBeInTheDocument();
    expect(within(sel).getByRole("button", { name: /overlay curves/i })).toBeInTheDocument();
  });

  it("closes with its ✕, clearing the selection", async () => {
    renderBoard(`/ws/test/app/my-app?sel=${v(1)}`);
    fireEvent.click(within(await bar()).getByRole("button", { name: "Clear selection" }));
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([]));
    noBar();
  });

  it("pads the page bottom while it shows", async () => {
    renderBoard(`/ws/test/app/my-app?sel=${v(1)}`);
    await bar();
    expect(document.querySelector(".sel-bar-spacer")).not.toBeNull();
  });
});

describe("Escape clears the selection", () => {
  it("from the page or a row checkbox", async () => {
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    fireEvent.click(checkbox(1));
    await bar();
    fireEvent.keyDown(checkbox(1), { key: "Escape" });
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([]));
    noBar();

    fireEvent.click(checkbox(2));
    await bar();
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([]));
  });

  it("but not while typing in a field", async () => {
    renderBoard(`/ws/test/app/my-app?sel=${v(1)}`);
    await bar();
    fireEvent.keyDown(screen.getByPlaceholderText(/search/i), { key: "Escape" });
    expect(urlParams().getAll("sel")).toEqual([v(1)]);
    expect(screen.getByRole("region", { name: "Selection" })).toBeInTheDocument();
  });

  it("nor while a dialog is open", async () => {
    renderBoard(`/ws/test/app/my-app?sel=${v(1)}`);
    fireEvent.click(within(await bar()).getByRole("button", { name: "Archive" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(urlParams().getAll("sel")).toEqual([v(1)]);
  });
});

describe("the header checkbox", () => {
  it("sits in the check column and selects every loaded row, then clears them", async () => {
    renderBoard();
    const all = await headerBox();
    expect(all.closest("th")).toHaveAttribute("data-col-id", "check");
    expect(all).not.toBeChecked();
    expect(all).not.toBePartiallyChecked();
    fireEvent.click(all);
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual(ALL));
    expect(await headerBox()).toBeChecked();
    fireEvent.click(await headerBox());
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([]));
  });

  it("is indeterminate while only some rows are selected, and then selects the rest", async () => {
    renderBoard(`/ws/test/app/my-app?sel=${v(2)}`);
    await waitFor(async () => expect(await headerBox()).toBePartiallyChecked());
    fireEvent.click(await headerBox());
    await waitFor(() => expect([...urlParams().getAll("sel")].sort()).toEqual(ALL));
  });

  it("clears only the rows on screen", async () => {
    const qs = ["off-screen", ...ALL].map((s) => `sel=${s}`).join("&");
    renderBoard(`/ws/test/app/my-app?${qs}`);
    await waitFor(async () => expect(await headerBox()).toBeChecked());
    fireEvent.click(await headerBox());
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual(["off-screen"]));
  });
});
