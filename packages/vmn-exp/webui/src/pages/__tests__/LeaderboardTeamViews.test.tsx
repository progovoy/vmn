/** Plan 28 P4 on the runs board: a column per tag key (`show=t:<key>`,
 *  offered from the facets' `tag_keys`, sorted server-side by
 *  `sort=tags.<key>`), the app's team views (from its status) in the Views
 *  menu, and the page's default team view applied on a bare landing. */
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
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
const appStatus = vi.hoisted(() => vi.fn());
vi.mock("../../apiShell", () => ({ apiShell: { appStatus: () => appStatus() } }));
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
const STATUS = {
  total: 2, counts: { created: 0, running: 0, stuck: 0, succeeded: 2, failed: 0 }, failed_recent: 0, rollup: null,
};
const VIEWS = [
  { name: "health", page: "runs", search: "?show=t%3Ahealth&sort=tags.health&order=asc", default: true },
  { name: "outer only", page: "jobs", search: "?sort=job%3Aattention", default: true },
  { name: "failed", page: "runs", search: "?status=failed", default: false },
];
const FACETS = {
  branches: ["main"], metric_keys: [], param_keys: [], tag_keys: ["health", "state"],
  param_values: {}, parented: 0, total: 2,
};
const head = (id: string) => document.querySelector(`thead th[data-col-id="${id}"]`) as HTMLElement;
const cells = (id: string) => [...document.querySelectorAll(`tbody td[data-col-id="${id}"]`)].map((c) => c.textContent);

const ROWS = [row(1, { tags: { health: "unstable" } }), row(2, { tags: { state: "ok" } })];

async function board(path = "/ws/test/app/my-app") {
  renderBoard(path);
  await screen.findByText("0.0.1-dev.x");
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockResolvedValue(FACETS);
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page(ROWS));
  m.experimentsPaged.mockResolvedValue({ rows: ROWS, total: 2 });
  appStatus.mockResolvedValue(STATUS);
});

describe("tag columns", () => {
  it("show a tag key's value per run, — without one", async () => {
    await board("/ws/test/app/my-app?show=t:health");
    expect(head("t:health")).toHaveTextContent("health");
    expect(cells("t:health")).toEqual(["unstable", "—"]);
    expect(head("t:state")).toBeNull();
  });

  it("sort by tags.<key>, a to z first, then flip", async () => {
    await board("/ws/test/app/my-app?show=t:health");
    fireEvent.click(head("t:health"));
    await waitFor(() => expect(urlParams().get("sort")).toBe("tags.health"));
    expect(urlParams().get("order")).toBe("asc");
    await waitFor(() => expect(m.experimentsPaged).toHaveBeenCalledWith(
      "test", "my-app", expect.objectContaining({ sort: "tags.health", order: "asc" })));
    fireEvent.click(head("t:health"));
    await waitFor(() => expect(urlParams().get("order")).toBe("desc"));
  });

  it("are offered in the column picker from the facets' tag keys", async () => {
    await board();
    fireEvent.click(screen.getByRole("button", { name: /Columns/ }));
    const box = await screen.findByLabelText("state");
    fireEvent.click(box);
    await waitFor(() => expect(urlParams().getAll("show")).toContain("t:state"));
    expect(cells("t:state")).toEqual(["—", "ok"]);
  });
});

describe("team views on the runs board", () => {
  it("are listed above my views, only the page's", async () => {
    appStatus.mockResolvedValue({ ...STATUS, views: VIEWS.map((v) => ({ ...v, default: false })) });
    await board("/ws/test/app/my-app?sort=idx");
    fireEvent.click(screen.getByRole("button", { name: /^Views/ }));
    const team = await screen.findByRole("group", { name: "Team views" });
    expect(within(team).getAllByRole("menuitem").map((el) => el.textContent)).toEqual(["health", "failed"]);
  });

  it("apply the page's default on a bare landing, once", async () => {
    appStatus.mockResolvedValue({ ...STATUS, views: VIEWS });
    await board();
    await waitFor(() => expect(urlParams().get("sort")).toBe("tags.health"));
    expect(urlParams().getAll("show")).toEqual(["t:health"]);
    expect(urlParams().get("status")).toBeNull();
  });

  it("leave a URL with view params alone", async () => {
    appStatus.mockResolvedValue({ ...STATUS, views: VIEWS });
    await board("/ws/test/app/my-app?status=succeeded");
    await waitFor(() => expect(appStatus).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(urlParams().get("sort")).toBeNull();
    expect(urlParams().get("status")).toBe("succeeded");
  });
});
