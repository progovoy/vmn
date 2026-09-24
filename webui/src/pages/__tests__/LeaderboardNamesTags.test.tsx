import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

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
    facets: vi.fn(),
    experiment: vi.fn(),
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
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page([
    row(1, { name: "baseline", tags: { team: "vision", stage: "prod" } }),
    row(2),
  ]));
});

describe("run names and tags in the table", () => {
  it("links a named run by its name and still shows the verstr", async () => {
    renderBoard();
    const link = await screen.findByRole("link", { name: "baseline" });
    expect(link).toHaveAttribute("href", "/ws/test/app/my-app/run/0.0.1-dev.x");
    expect(within(link.closest("tr")!).getByText("0.0.1-dev.x")).toBeInTheDocument();
    // An unnamed run falls back to its verstr.
    expect(screen.getByRole("link", { name: "0.0.2-dev.x" })).toBeInTheDocument();
  });

  it("shows tags as chips in a tags column", async () => {
    renderBoard();
    const tr = (await screen.findByRole("link", { name: "baseline" })).closest("tr")!;
    expect(within(tr).getByText("team: vision")).toHaveClass("tag-chip");
    expect(within(tr).getByText("stage: prod")).toBeInTheDocument();
    expect(within(document.querySelector("thead")!).getByText("tags")).toBeInTheDocument();
  });

  it("hides the tags column from the column picker, in the URL", async () => {
    renderBoard();
    await screen.findByRole("link", { name: "baseline" });
    fireEvent.click(screen.getByTitle("Columns"));
    fireEvent.click(screen.getByLabelText("tags"));
    await waitFor(() => expect(urlParams().getAll("hide")).toEqual(["c:tags"]));
    expect(within(document.querySelector("thead")!).queryByText("tags")).toBeNull();
    expect(screen.queryByText("team: vision")).toBeNull();
  });

  it("has no tags column when no run carries tags", async () => {
    m.experiments.mockResolvedValue(page([row(1), row(2)]));
    renderBoard();
    await screen.findByRole("link", { name: "0.0.1-dev.x" });
    expect(within(document.querySelector("thead")!).queryByText("tags")).toBeNull();
  });
});
