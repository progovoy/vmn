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
const v = (i: number) => `0.0.${i}-dev.x`;
const link = (i: number) => screen.queryByRole("link", { name: v(i) });
const toggle = (i: number) => screen.getByRole("button", { name: new RegExp(`(Expand|Collapse) ${v(i)}`) });

/** An outer run @1 with inner runs @2..@(n+1), and a lone run after them. */
function sweep(n: number) {
  const inner = Array.from({ length: n }, (_, k) => k + 2);
  return [
    row(1, { kind: "outer", children: inner.map(v), depth: 0, parent: null }),
    ...inner.map((i) => row(i, { kind: "inner", parent: v(1), depth: 1 })),
    row(n + 2, { depth: 0, parent: null }),
  ];
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiment.mockResolvedValue({ metadata: { verstr: "x" }, metrics: {}, series: {}, patches: {} });
});

describe("folding an outer run's inner runs", () => {
  it("starts shut and the arrow shows the inner runs under it, then hides them", async () => {
    m.experiments.mockResolvedValue(page(sweep(3)));
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    expect(toggle(1)).toHaveAttribute("aria-expanded", "false");
    expect(link(2)).toBeNull();

    fireEvent.click(toggle(1));
    await waitFor(() => expect(link(2)).toBeInTheDocument());
    expect(toggle(1)).toHaveAttribute("aria-expanded", "true");
    expect(urlParams().getAll("expand")).toEqual([v(1)]);
    const order = [...document.querySelectorAll("tbody tr.row .run-link")].map((a) => a.textContent);
    expect(order).toEqual([v(1), v(2), v(3), v(4), v(5)]);
    expect(link(2)!.closest(".nest")!.querySelector(".nest-mark")).not.toBeNull();

    fireEvent.click(toggle(1));
    await waitFor(() => expect(link(2)).toBeNull());
    expect(toggle(1)).toHaveAttribute("aria-expanded", "false");
    expect(urlParams().getAll("expand")).toEqual([]);
  });

  it("opens a big sweep the same way", async () => {
    m.experiments.mockResolvedValue(page(sweep(25)));
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    fireEvent.click(toggle(1));
    await waitFor(() => expect(link(26)).toBeInTheDocument());
  });

  it("keeps old URLs working: expand= opens, a legacy collapse= stays shut", async () => {
    m.experiments.mockResolvedValue(page(sweep(3)));
    renderBoard(`/ws/test/app/my-app?expand=${v(1)}`);
    expect(await screen.findByRole("link", { name: v(2) })).toBeInTheDocument();
  });

  it("fetches inner runs that are not loaded once, showing a loading row meanwhile", async () => {
    const [outer, ...rest] = sweep(2);
    const inner = rest.slice(0, 2);
    m.experiments.mockResolvedValue(page([outer, rest[2]], 10));
    let answer: (v: { rows: typeof inner; total: number }) => void = () => {};
    m.experimentsPaged.mockImplementation(() => new Promise((res) => { answer = res; }));
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    fireEvent.click(toggle(1));
    expect(await screen.findByText(/loading inner runs/i)).toBeInTheDocument();
    expect(m.experimentsPaged).toHaveBeenCalledTimes(1);
    expect(m.experimentsPaged.mock.calls[0][2]).toMatchObject({ query: `parent = "${v(1)}"`, offset: 0 });
    answer({ rows: inner, total: 2 });
    expect(await screen.findByRole("link", { name: v(2) })).toBeInTheDocument();
    expect(screen.queryByText(/loading inner runs/i)).toBeNull();

    fireEvent.click(toggle(1));
    fireEvent.click(toggle(1));
    expect(await screen.findByRole("link", { name: v(3) })).toBeInTheDocument();
    expect(m.experimentsPaged).toHaveBeenCalledTimes(1);
  });

  it("lets an inner row be selected like any row", async () => {
    m.experiments.mockResolvedValue(page(sweep(2)));
    renderBoard(`/ws/test/app/my-app?expand=${v(1)}`);
    await screen.findByRole("link", { name: v(2) });
    fireEvent.click(screen.getByRole("checkbox", { name: `Select ${v(2)}` }));
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([v(2)]));
  });

  it("moves the keyboard through the inner rows", async () => {
    m.experiments.mockResolvedValue(page(sweep(2)));
    renderBoard(`/ws/test/app/my-app?expand=${v(1)}`);
    await screen.findByRole("link", { name: v(2) });
    const rowOf = (i: number) => screen.getByRole("link", { name: v(i) }).closest("tr")!;
    fireEvent.keyDown(screen.getByRole("grid"), { key: "j" });
    fireEvent.keyDown(rowOf(1), { key: "j" });
    expect(rowOf(2)).toHaveFocus();
  });

  it("keeps the subtitle's top-level count once inner rows are shown", async () => {
    m.experiments.mockResolvedValue(page(sweep(3)));
    renderBoard(`/ws/test/app/my-app?expand=${v(1)}`);
    await screen.findByRole("link", { name: v(2) });
    expect(document.querySelector(".page-sub")?.textContent).toContain("2 runs · 5 incl. inner");
  });

  it("counts only the top-level runs on a filtered board with an outer open", async () => {
    const rows = sweep(3);
    m.experiments.mockResolvedValue(page([rows[0], rows[4]], 2));
    m.experimentsPaged.mockResolvedValue({ rows: rows.slice(1, 4), total: 3 });
    renderBoard(`/ws/test/app/my-app?status=succeeded&expand=${v(1)}`);
    await screen.findByRole("link", { name: v(2) });
    expect(document.querySelector(".page-sub")?.textContent).toContain("2 runs");
    expect(document.querySelector(".page-sub")?.textContent).not.toContain("5 of");
  });
});
