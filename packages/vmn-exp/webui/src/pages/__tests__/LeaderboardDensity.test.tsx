/** The board's row density (plan 23 W8): `density=compact|comfortable` in
 *  the URL, else the user's last pick, else comfortable. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    experimentGroups: vi.fn(),
    experimentGroupRows: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    config: vi.fn(),
    experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count, estimateSize }: { count: number; estimateSize: () => number }) => ({
    getTotalSize: () => count * estimateSize(),
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * estimateSize(), size: estimateSize(), end: (index + 1) * estimateSize(),
      })),
  }),
}));

import { api } from "../../api";
import type { RunGroup } from "../../apiGroups";
import { DENSITY_KEY } from "../../hooks/useLeaderboardView";
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;
const NAMED = row(1, { name: "baseline", branch: "feature-x", metrics: { loss: 0.5 } });
const rowOf = () => screen.getByRole("link", { name: "baseline" }).closest("tr")!;
const densityGroup = () => screen.getByRole("group", { name: "Row density" });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.config.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiment.mockResolvedValue({ metadata: { verstr: "x" }, metrics: {}, series: {}, patches: {} });
  m.experiments.mockResolvedValue(page([NAMED, row(2)]));
});

describe("row density", () => {
  it("is comfortable by default: two-line rows with the verstr and branch under the name", async () => {
    renderBoard();
    await screen.findByRole("link", { name: "baseline" });
    expect(rowOf().style.height).toBe("48px");
    expect(rowOf().querySelector(".exp-branch")?.textContent).toContain("feature-x");
    expect(within(densityGroup()).getByRole("button", { name: "Comfortable" })).toHaveAttribute("aria-pressed", "true");
  });

  it("density=compact gives one-line 32px rows, the sub-line moving to the name's tooltip", async () => {
    renderBoard("/ws/test/app/my-app?density=compact");
    await screen.findByRole("link", { name: "baseline" });
    expect(rowOf().style.height).toBe("32px");
    expect(rowOf().querySelector(".exp-branch")).toBeNull();
    const title = screen.getByRole("link", { name: "baseline" }).getAttribute("title") ?? "";
    expect(title).toContain(v(1));
    expect(title).toContain("feature-x");
    expect(screen.getByRole("grid")).toHaveClass("compact");
    expect(within(densityGroup()).getByRole("button", { name: "Compact" })).toHaveAttribute("aria-pressed", "true");
  });

  it("the toolbar toggle writes density= and remembers the pick for boards without it", async () => {
    const first = renderBoard();
    await screen.findByRole("link", { name: "baseline" });
    fireEvent.click(within(densityGroup()).getByRole("button", { name: "Compact" }));
    await waitFor(() => expect(urlParams().get("density")).toBe("compact"));
    expect(rowOf().style.height).toBe("32px");
    expect(localStorage.getItem(DENSITY_KEY)).toBe("compact");
    first.unmount();

    renderBoard();
    await screen.findByRole("link", { name: "baseline" });
    expect(rowOf().style.height).toBe("32px");
  });

  it("the URL beats the remembered pick", async () => {
    localStorage.setItem(DENSITY_KEY, "compact");
    renderBoard("/ws/test/app/my-app?density=comfortable");
    await screen.findByRole("link", { name: "baseline" });
    expect(rowOf().style.height).toBe("48px");
  });

  it("ignores an unknown density", async () => {
    renderBoard("/ws/test/app/my-app?density=huge");
    await screen.findByRole("link", { name: "baseline" });
    expect(rowOf().style.height).toBe("48px");
  });
});

describe("row density, grouped", () => {
  const INNER = [row(2, { kind: "inner", parent: v(1), depth: 1 }), row(3, { kind: "inner", parent: v(1), depth: 1 })];
  const group = (): RunGroup => ({
    key: v(1), label: v(1),
    target: { verstr: v(1), idx: 1, name: "sweep", status: "succeeded", tree_status: "succeeded", metrics: {} },
    counts: { total: 5, running: 0, waiting: 0, done: 5, failed: 0, stuck: 0 },
    aggregates: {}, rows: INNER, rows_total: 5, rows_unfiltered: 5, clause: null, loose: false,
  });

  beforeEach(() => {
    m.experiments.mockResolvedValue(page([row(1, { kind: "outer", name: "sweep", children: [v(2), v(3)] }), ...INNER]));
    m.facets.mockResolvedValue({
      branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {}, parented: 2, total: 3,
    });
    m.experimentGroups.mockResolvedValue({ groups: [group()], total_groups: 1, total_rows: 3 });
  });

  it("header, member and +N more rows all follow the compact height", async () => {
    renderBoard("/ws/test/app/my-app?density=compact");
    await waitFor(() => expect(document.querySelector("tbody tr.group-row")).not.toBeNull());
    const rows = [...document.querySelectorAll<HTMLElement>("tbody tr[data-row-index]")];
    expect(rows.some((r) => r.classList.contains("group-more"))).toBe(true);
    expect(new Set(rows.map((r) => r.style.height))).toEqual(new Set(["32px"]));
  });
});
