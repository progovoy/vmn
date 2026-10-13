import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    experiment: vi.fn(),
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
  appStatus.mockResolvedValue(KNOWN_APP);
  m.apps.mockResolvedValue([{ name: "my/app", experiments: 1, versions: 1 }]);
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
        "test", "my-app", "idx", "running",
        '(metrics.loss < 1) and (name ~ "bat" or verstr ~ "bat" or note ~ "bat" or branch ~ "bat")',
      ),
    );
    const tokens = within(screen.getByRole("list", { name: "Active filters" })).getAllByRole("listitem");
    expect(tokens.map((t) => t.getAttribute("data-token")))
      .toEqual(['status = "running"', 'text ~ "bat"', "metrics.loss < 1"]);
    expect(screen.getByRole("button", { name: "running" })).toHaveAttribute("aria-pressed", "true");
  });

  it("filters by branch on the server", async () => {
    renderBoard("/ws/test/app/my-app?branch=feat");
    await waitFor(() =>
      expect(m.experiments).toHaveBeenCalledWith(
        "test", "my-app", "idx", undefined, 'branch = "feat"',
      ),
    );
  });

  it("puts a typed status filter into the URL", async () => {
    renderBoard();
    fireEvent.click(await screen.findByRole("button", { name: "failed" }));
    await waitFor(() => expect(urlParams().get("status")).toBe("failed"));
  });

  it("puts a hand-typed status clause into ?status=, not ?q=", async () => {
    renderBoard();
    const box = await screen.findByLabelText("Filter query");
    fireEvent.change(box, { target: { value: 'status = "failed"' } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(urlParams().get("status")).toBe("failed"));
    expect(urlParams().get("q")).toBeNull();
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
    expect(screen.getByRole("button", { name: /^code diff$/i })).toBeEnabled();
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
    fireEvent.click(await screen.findByRole("button", { name: "New run" }));
    await screen.findByText("new-form");
    expect(urlParams().get("new")).toBe("1");
    expect(urlParams().get("status")).toBe("running");
    expect(urlParams().get("sort")).toBe("loss");
  });
});
