import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

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
vi.mock("../../components/MetricBarChart", () => ({ default: () => <div>bar-chart</div> }));
vi.mock("../../components/NewExperiment", () => ({ default: () => <div>new-form</div> }));
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
  m.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page([row(1, { metrics: { loss: 0.2 }, params: { model: "m1" } })]));
  m.experimentsPaged.mockResolvedValue({ rows: [row(1, { metrics: { loss: 0.2 } })], total: 1 });
});

describe("leaderboard view state lives in the URL", () => {
  it("requests the sort and order the URL names", async () => {
    renderBoard("/ws/test/app/my-app?sort=loss&order=desc");
    await waitFor(() =>
      expect(m.experimentsPaged).toHaveBeenCalledWith(
        "test", "my-app", expect.objectContaining({ sort: "loss", order: "desc", offset: 0 }),
      ),
    );
    expect(m.experiments).not.toHaveBeenCalled();
  });

  it("writes a clicked sort into the URL", async () => {
    renderBoard();
    fireEvent.click(await screen.findByTitle(/sort by loss/));
    await waitFor(() => expect(urlParams().get("sort")).toBe("loss"));
    expect(urlParams().get("order")).toBe("asc");
  });

  it("restores status, query and search from the URL into the request and the inputs", async () => {
    renderBoard("/ws/test/app/my-app?status=running&q=metrics.loss%20%3C%201&search=bat");
    await waitFor(() =>
      expect(m.experiments).toHaveBeenCalledWith(
        "test", "my-app", "timestamp", "running",
        '(metrics.loss < 1) and (verstr ~ "bat" or note ~ "bat" or branch ~ "bat")',
      ),
    );
    expect(screen.getByLabelText("Filter query")).toHaveValue("metrics.loss < 1");
    expect(screen.getByPlaceholderText(/search/i)).toHaveValue("bat");
    expect(screen.getByRole("button", { name: "running" })).toHaveAttribute("aria-pressed", "true");
  });

  it("filters by branch on the server", async () => {
    renderBoard("/ws/test/app/my-app?branch=feat");
    await waitFor(() =>
      expect(m.experiments).toHaveBeenCalledWith(
        "test", "my-app", "timestamp", undefined, 'branch = "feat"',
      ),
    );
  });

  it("puts a typed status filter into the URL", async () => {
    renderBoard();
    fireEvent.click(await screen.findByRole("button", { name: "failed" }));
    await waitFor(() => expect(urlParams().get("status")).toBe("failed"));
  });

  it("restores the chart view from the URL", async () => {
    renderBoard("/ws/test/app/my-app?view=bar");
    expect(await screen.findByText("bar-chart")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bar" }).className).toContain("primary");
  });

  it("keeps the selection in the URL", async () => {
    m.experiments.mockResolvedValue(page([row(1), row(2)]));
    renderBoard("/ws/test/app/my-app?sel=0.0.1-dev.x");
    const second = (await screen.findByText("0.0.2-dev.x")).closest("tr")!;
    fireEvent.click(within(second).getByRole("checkbox"));
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual(["0.0.1-dev.x", "0.0.2-dev.x"]));
    expect(screen.getByRole("button", { name: /code diff of 2 selected/i })).toBeInTheDocument();
  });

  it("hides the columns the URL hides", async () => {
    renderBoard("/ws/test/app/my-app?hide=p:model&hide=m:loss");
    await screen.findByText("0.0.1-dev.x");
    const head = document.querySelector("thead") as HTMLElement;
    expect(within(head).queryByText("model")).toBeNull();
    expect(within(head).queryByText(/^loss/)).toBeNull();
  });

  it("opening the create form keeps the other params", async () => {
    renderBoard("/ws/test/app/my-app?status=running&sort=loss&order=asc");
    fireEvent.click(await screen.findByRole("button", { name: "+ New experiment" }));
    await screen.findByText("new-form");
    expect(urlParams().get("new")).toBe("1");
    expect(urlParams().get("status")).toBe("running");
    expect(urlParams().get("sort")).toBe("loss");
  });
});
