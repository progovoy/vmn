/** Plan 20 C3 on the board: the header's keyboard sort and column menu. */
import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderBoard, row, page, urlParams } from "./leaderboardHarness";

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    metricsSchema: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
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

const mockedApi = api as unknown as {
  experiments: ReturnType<typeof vi.fn>;
  experimentsPaged: ReturnType<typeof vi.fn>;
  metricsSchema: ReturnType<typeof vi.fn>;
};

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
  mockedApi.experimentsPaged?.mockResolvedValue(undefined);
});

const metricHeads = () =>
  [...document.querySelectorAll("thead th[data-col-id^='m:']")].map((th) => th.getAttribute("data-col-id"));
const head = (id: string) => document.querySelector(`thead th[data-col-id="${id}"]`) as HTMLElement;

async function board(path = "/ws/test/app/my-app") {
  mockedApi.experiments.mockResolvedValue(page([
    row(1, { metrics: { loss: 0.3, acc: 0.8 } }),
    row(2, { metrics: { loss: 0.2, acc: 0.7 } }),
  ]));
  renderBoard(path);
  await waitFor(() => expect(head("m:loss")).toBeTruthy());
}

const choose = (col: string, item: string) => {
  fireEvent.click(screen.getByRole("button", { name: `Column menu: ${col}` }));
  fireEvent.click(screen.getByRole("menuitem", { name: item }));
};

describe("Leaderboard column menu (C3)", () => {
  it("Enter on a header's sort button sorts the board and aria-sort follows", async () => {
    await board();
    expect(head("m:loss")).toHaveAttribute("aria-sort", "none");
    fireEvent.keyDown(within(head("m:loss")).getByRole("button", { name: /^sort by loss/ }), { key: "Enter" });
    await waitFor(() => expect(urlParams().get("sort")).toBe("loss"));
    // loss is lower-is-better, so its first sort is ascending (best first).
    expect(head("m:loss")).toHaveAttribute("aria-sort", "ascending");
    fireEvent.keyDown(within(head("m:loss")).getByRole("button", { name: /^sort by loss/ }), { key: " " });
    await waitFor(() => expect(head("m:loss")).toHaveAttribute("aria-sort", "descending"));
  });

  it("Move right moves the column in the header", async () => {
    await board();
    expect(metricHeads()).toEqual(["m:acc", "m:loss"]);
    choose("acc", "Move right");
    await waitFor(() => expect(metricHeads()).toEqual(["m:loss", "m:acc"]));
  });

  it("Hide column hides it", async () => {
    await board();
    choose("acc", "Hide column");
    await waitFor(() => expect(head("m:acc")).toBeNull());
    expect(urlParams().getAll("hide")).toEqual(["m:acc"]);
  });

  it("Hide column hides a column turned on with show=", async () => {
    mockedApi.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
    await board("/ws/test/app/my-app?show=m%3Aacc");
    await waitFor(() => expect(head("m:acc")).toBeTruthy());
    choose("acc", "Hide column");
    await waitFor(() => expect(head("m:acc")).toBeNull());
    expect(urlParams().getAll("show")).toEqual([]);
  });

  it("Hide column hides a schema-hidden metric shown with its older hide= key", async () => {
    mockedApi.metricsSchema.mockResolvedValue({ acc: { hidden: true } });
    await board("/ws/test/app/my-app?hide=m%3Aacc");
    await waitFor(() => expect(head("m:acc")).toBeTruthy());
    choose("acc", "Hide column");
    await waitFor(() => expect(head("m:acc")).toBeNull());
  });

  it("Pin column pins it after the experiment column", async () => {
    await board();
    choose("loss", "Pin column");
    await waitFor(() => expect(urlParams().getAll("pin")).toEqual(["m:loss"]));
    expect(metricHeads()).toEqual(["m:loss", "m:acc"]);
    choose("loss", "Unpin column");
    await waitFor(() => expect(urlParams().getAll("pin")).toEqual([]));
  });

  it("a goal metric pinned by default offers Unpin, which pins nothing (pin=-)", async () => {
    mockedApi.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
    await board();
    await waitFor(() => expect(head("m:loss").style.zIndex).toBe("3"));
    choose("loss", "Unpin column");
    await waitFor(() => expect(urlParams().getAll("pin")).toEqual(["-"]));
    expect(head("m:loss").style.zIndex).toBe("2");
  });

  it("pinning back to the default pins drops pin=", async () => {
    mockedApi.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
    await board("/ws/test/app/my-app?pin=-");
    await waitFor(() => expect(screen.getByRole("button", { name: "Column menu: loss" })).toBeTruthy());
    choose("loss", "Pin column");
    await waitFor(() => expect(urlParams().has("pin")).toBe(false));
    expect(head("m:loss").style.zIndex).toBe("3");
  });

  it("a pinned column moves among the pinned ones", async () => {
    await board("/ws/test/app/my-app?pin=m%3Aacc&pin=m%3Aloss");
    expect(metricHeads()).toEqual(["m:acc", "m:loss"]);
    choose("loss", "Move left");
    await waitFor(() => expect(metricHeads()).toEqual(["m:loss", "m:acc"]));
  });
});
