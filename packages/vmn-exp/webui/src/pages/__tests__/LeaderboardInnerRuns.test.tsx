import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

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
const COUNTS = ["c:total", "c:waiting", "c:running", "c:done", "c:failed"];
const colIds = () => [...document.querySelectorAll("thead th[data-col-id]")].map((th) => (th as HTMLElement).dataset.colId);
const group = () => screen.queryByRole("columnheader", { name: "Inner runs" });
const rowOf = (verstr: string) =>
  [...document.querySelectorAll("tbody tr.row")].find((r) => r.textContent?.includes(verstr)) as HTMLElement;
const cell = (verstr: string, col: string) => rowOf(verstr)?.querySelector(`td[data-col-id="${col}"]`)?.textContent;

const outer = (i: number) => row(i, {
  kind: "outer", depth: 0, children: ["a", "b", "c", "d"],
  child_counts: { created: 1, running: 2, succeeded: 1 },
});
const single = (i: number) => row(i, { kind: "single", depth: 0, children: [], status: "running" });

function serve(rows: ReturnType<typeof row>[]) {
  m.experiments.mockResolvedValue(page(rows));
  m.experimentsPaged.mockResolvedValue({ rows, total: rows.length });
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
});

describe("the leaderboard's inner-run columns", () => {
  it("sit under one Inner runs header, described for screen readers and on hover", async () => {
    serve([outer(2), single(1)]);
    renderBoard();
    await screen.findByText("0.0.2-dev.x");
    const g = group()!;
    expect(g).not.toBeNull();
    expect(g).toHaveAttribute("scope", "colgroup");
    expect(g).toHaveAttribute("colspan", "5");
    const text = "Counts of this run's inner runs (sweep trials, fleet pods)";
    expect(g).toHaveAttribute("title", text);
    expect(g).toHaveAccessibleDescription(text);
    COUNTS.forEach((c) => expect(colIds()).toContain(c));
  });

  it("keeps every group-row cell in the accessibility tree, so Inner runs heads its own columns", async () => {
    serve([outer(1)]);
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    const cells = [...document.querySelectorAll(".lb-group-row > *")] as HTMLTableCellElement[];
    cells.forEach((c) => expect(c).not.toHaveAttribute("aria-hidden"));
    const before = cells.slice(0, cells.indexOf(group() as HTMLTableCellElement));
    const offset = before.reduce((n, c) => n + c.colSpan, 0);
    expect(colIds()[offset]).toBe("c:total");
  });

  it("keeps the Inner runs label readable when its block scrolls under the pinned columns", async () => {
    serve([outer(1)]);
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    const exp = document.querySelector('thead th[data-col-id="experiment"]') as HTMLElement;
    const edge = Number.parseFloat(exp.style.left) + Number.parseFloat(exp.style.width);
    const label = (group() as HTMLElement).querySelector(".lb-group-label") as HTMLElement;
    expect(label.textContent).toBe("Inner runs");
    expect(label.style.position).toBe("sticky");
    expect(Number.parseFloat(label.style.left)).toBe(edge);
  });

  it("keeps the column row stuck below the group row", async () => {
    serve([outer(1)]);
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    const th = document.querySelector('thead th[data-col-id="c:total"]') as HTMLElement;
    expect(th.style.position).toBe("sticky");
    expect(Number.parseFloat(th.style.top)).toBeGreaterThan(0);
    expect((group() as HTMLElement).style.top).toBe("0px");
  });

  it("counts an outer run's inner runs and leaves other rows' cells empty", async () => {
    serve([outer(2), single(1)]);
    renderBoard();
    await screen.findByText("0.0.2-dev.x");
    expect(cell("0.0.2-dev.x", "c:total")).toBe("4");
    expect(cell("0.0.2-dev.x", "c:running")).toBe("2");
    expect(cell("0.0.2-dev.x", "c:failed")).toBe("0");
    COUNTS.forEach((c) => expect(cell("0.0.1-dev.x", c)).toBe(""));
  });

  it("are left out, group header and all, when no run on the board is an outer run", async () => {
    serve([single(2), single(1)]);
    renderBoard();
    await screen.findByText("0.0.2-dev.x");
    COUNTS.forEach((c) => expect(colIds()).not.toContain(c));
    expect(group()).toBeNull();
  });

  it("show a count column the user turns on in the column picker, and keep it in the URL", async () => {
    serve([single(1)]);
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    fireEvent.click(screen.getByRole("button", { name: /columns/i }));
    const box = screen.getByRole("checkbox", { name: "waiting" });
    expect(box).not.toBeChecked();
    fireEvent.click(box);
    await waitFor(() => expect(colIds()).toContain("c:waiting"));
    expect(urlParams().getAll("show")).toContain("c:waiting");
    expect(colIds()).not.toContain("c:total");
  });

  it("show the columns a saved view lists in show=, even without outer runs", async () => {
    serve([single(1)]);
    renderBoard("/ws/test/app/my-app?show=c:total&show=c:failed");
    await screen.findByText("0.0.1-dev.x");
    expect(colIds()).toEqual(expect.arrayContaining(["c:total", "c:failed"]));
    expect(colIds()).not.toContain("c:waiting");
    expect(cell("0.0.1-dev.x", "c:total")).toBe("");
  });

  it("stay hidden once the user turns them off, whatever the rows", async () => {
    serve([single(1)]);
    renderBoard("/ws/test/app/my-app?show=c:total");
    await screen.findByText("0.0.1-dev.x");
    fireEvent.click(screen.getByRole("button", { name: /columns/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: "total" }));
    await waitFor(() => expect(colIds()).not.toContain("c:total"));
    expect(urlParams().getAll("show")).not.toContain("c:total");
    expect(urlParams().getAll("hide")).toContain("c:total");
  });

  it("leave the inner count out of the experiment cell while one shows, and say it there once all are hidden", async () => {
    serve([outer(2)]);
    const { unmount } = renderBoard();
    await screen.findByText("0.0.2-dev.x");
    const exp = () => rowOf("0.0.2-dev.x").querySelector('td[data-col-id="experiment"]')!;
    expect(exp().textContent).not.toMatch(/4 inner/);
    unmount();
    renderBoard(`/ws/test/app/my-app?${COUNTS.map((c) => `hide=${c}`).join("&")}`);
    await screen.findByText("0.0.2-dev.x");
    expect(exp().textContent).toMatch(/4 inner/);
  });

  it("read the single inner column's links: show=c:inner shows all five, hide=c:inner hides them", async () => {
    serve([single(1)]);
    const { unmount } = renderBoard("/ws/test/app/my-app?show=c:inner");
    await screen.findByText("0.0.1-dev.x");
    expect(colIds()).toEqual(expect.arrayContaining(COUNTS));
    expect(group()).not.toBeNull();
    unmount();
    serve([outer(1)]);
    renderBoard("/ws/test/app/my-app?hide=c:inner");
    await screen.findByText("0.0.1-dev.x");
    COUNTS.forEach((c) => expect(colIds()).not.toContain(c));
    expect(group()).toBeNull();
  });

  it("let a count's own key beat c:inner", async () => {
    serve([outer(1)]);
    renderBoard("/ws/test/app/my-app?hide=c:inner&show=c:failed");
    await screen.findByText("0.0.1-dev.x");
    expect(colIds().filter((c) => COUNTS.includes(c!))).toEqual(["c:failed"]);
  });
});
