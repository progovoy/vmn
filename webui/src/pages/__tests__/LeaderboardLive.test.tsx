import { describe, it, expect, vi, beforeEach, beforeAll, afterEach } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";

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
import { location, page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiment.mockResolvedValue({ metadata: { verstr: "x" }, metrics: {}, series: {}, patches: {} });
});
afterEach(() => { vi.useRealTimers(); });

describe("rows are links", () => {
  it("renders the experiment cell as a real link to the run", async () => {
    m.experiments.mockResolvedValue(page([row(1)]));
    renderBoard();
    const link = await screen.findByRole("link", { name: "0.0.1-dev.x" });
    expect(link).toHaveAttribute("href", "/ws/test/app/my-app/run/0.0.1-dev.x");
  });

  it("prefetches the run detail on hover and on focus", async () => {
    m.experiments.mockResolvedValue(page([row(1), row(2)]));
    renderBoard();
    fireEvent.mouseEnter(await screen.findByRole("link", { name: "0.0.1-dev.x" }));
    await waitFor(() => expect(m.experiment).toHaveBeenCalledWith("test", "my-app", "0.0.1-dev.x"));
    fireEvent.focus(screen.getByRole("link", { name: "0.0.2-dev.x" }));
    await waitFor(() => expect(m.experiment).toHaveBeenCalledWith("test", "my-app", "0.0.2-dev.x"));
  });
});

describe("first paint", () => {
  it("shows the toolbar, filters and skeleton rows before the rows arrive", async () => {
    m.experiments.mockImplementation(() => new Promise(() => {}));
    renderBoard();
    expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Filter query")).toBeInTheDocument();
    expect(document.querySelectorAll("tr.skeleton-row").length).toBeGreaterThan(0);
  });

  it("paints cached rows at once on Back, then revalidates", async () => {
    m.experiments.mockResolvedValue(page([row(1)]));
    renderBoard();
    fireEvent.click(await screen.findByRole("link", { name: "0.0.1-dev.x" }));
    fireEvent.click(await screen.findByRole("button", { name: "go-back" }));
    // Synchronously there: no skeleton, no wait.
    expect(screen.getByRole("link", { name: "0.0.1-dev.x" })).toBeInTheDocument();
    expect(document.querySelectorAll("tr.skeleton-row")).toHaveLength(0);
    await waitFor(() => expect(m.experiments).toHaveBeenCalledTimes(2));
  });

  it("restores the table's scroll offset on Back", async () => {
    m.experiments.mockResolvedValue(page(Array.from({ length: 50 }, (_, i) => row(i + 1))));
    renderBoard();
    await screen.findByRole("link", { name: "0.0.1-dev.x" });
    const scroller = document.querySelector(".tbl-scroll") as HTMLElement;
    scroller.scrollTop = 480;
    fireEvent.scroll(scroller);
    fireEvent.click(screen.getByRole("link", { name: "0.0.3-dev.x" }));
    fireEvent.click(await screen.findByRole("button", { name: "go-back" }));
    await waitFor(() =>
      expect((document.querySelector(".tbl-scroll") as HTMLElement).scrollTop).toBe(480),
    );
    expect(location.pathname).toBe("/ws/test/app/my-app");
  });
});

describe("paging", () => {
  it("loads the next page when the table is scrolled near its end", async () => {
    m.experiments.mockResolvedValue(page([row(1), row(2)], 3));
    m.experimentsPaged.mockResolvedValue({ rows: [row(3)], total: 3 });
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    const scroller = document.querySelector(".tbl-scroll") as HTMLElement;
    fireEvent.scroll(scroller);
    await waitFor(() =>
      expect(m.experimentsPaged).toHaveBeenCalledWith(
        "test", "my-app", expect.objectContaining({ offset: 2 }),
      ),
    );
    expect(await screen.findByText("0.0.3-dev.x")).toBeInTheDocument();
  });

  it("polls the first page plus running rows past it, by verstr", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    m.experiments.mockResolvedValue(page([row(1)], 2));
    m.experimentsPaged.mockResolvedValueOnce({ rows: [row(2, { status: "running", note: "old" })], total: 2 });
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    fireEvent.click(screen.getByRole("button", { name: /load more/i }));
    await screen.findByText("old");

    m.experimentsPaged.mockResolvedValue({ rows: [row(2, { status: "running", note: "new" })], total: 1 });
    await act(async () => { await vi.advanceTimersByTimeAsync(16_000); });
    await waitFor(() => expect(screen.getByText("new")).toBeInTheDocument());
    const byId = m.experimentsPaged.mock.calls.find(([, , o]) => /verstr in/.test(o.query ?? ""));
    expect(byId![2].query).toBe('verstr in ("0.0.2-dev.x")');
    expect(m.experiments.mock.calls.length).toBe(2);
  });
});

describe("filters", () => {
  it("fills the branch dropdown from the facets endpoint", async () => {
    m.facets.mockResolvedValue({ branches: ["main", "feat/x"], metric_keys: ["loss"], param_keys: [], total: 9 });
    m.experiments.mockResolvedValue(page([row(1)]));
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    await waitFor(() => expect(screen.getByRole("option", { name: "feat/x" })).toBeInTheDocument());
  });

  it("falls back to the loaded rows' branches without facets", async () => {
    m.experiments.mockResolvedValue(page([row(1, { branch: "dev" })]));
    renderBoard();
    await waitFor(() => expect(screen.getByRole("option", { name: "dev" })).toBeInTheDocument());
  });

  it("suggests metric fields from the facets as the query is typed", async () => {
    m.facets.mockResolvedValue({ branches: [], metric_keys: ["loss"], param_keys: ["lr"], total: 1 });
    m.experiments.mockResolvedValue(page([row(1)]));
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    const box = screen.getByLabelText("Filter query") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "metrics.l", selectionStart: 9 } });
    const list = await screen.findByRole("listbox");
    fireEvent.mouseDown(within(list).getByRole("option", { name: "metrics.loss" }));
    expect(box.value).toBe("metrics.loss ");
  });

  it("leaves search to the server: returned rows are never filtered out", async () => {
    m.experiments.mockResolvedValue(page([row(1, { note: "unrelated" })]));
    renderBoard("/ws/test/app/my-app?search=zzz");
    expect(await screen.findByText("0.0.1-dev.x")).toBeInTheDocument();
  });

  it("sorts by the when column on the server", async () => {
    m.experiments.mockResolvedValue(page([row(1)]));
    m.experimentsPaged.mockResolvedValue({ rows: [row(1)], total: 1 });
    renderBoard();
    fireEvent.click(await screen.findByTitle(/sort by time/i));
    await waitFor(() =>
      expect(m.experimentsPaged).toHaveBeenLastCalledWith(
        "test", "my-app", expect.objectContaining({ sort: "timestamp", order: "desc" }),
      ),
    );
  });

  it("labels the live toggle's off state", async () => {
    m.experiments.mockResolvedValue(page([row(1)]));
    renderBoard();
    const toggle = await screen.findByRole("button", { name: /live off/i });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: /^live$/i })).toHaveAttribute("aria-pressed", "true");
  });
});
