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
const colIds = () => [...document.querySelectorAll("thead th[data-col-id]")].map((th) => (th as HTMLElement).dataset.colId);
const rowOf = (verstr: string) =>
  [...document.querySelectorAll("tbody tr.row")].find((r) => r.textContent?.includes(verstr)) as HTMLElement;
const innerCell = (verstr: string) => rowOf(verstr)?.querySelector('td[data-col-id="c:inner"]') as HTMLElement;

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

describe("the leaderboard's inner column (C2)", () => {
  it("is one column with no header group, described for screen readers and on hover", async () => {
    serve([outer(2), single(1)]);
    renderBoard();
    await screen.findByText("0.0.2-dev.x");
    expect(colIds().filter((c) => c?.startsWith("c:") && !["c:started", "c:ended"].includes(c))).toEqual(["c:inner"]);
    expect(document.querySelector(".lb-group-row")).toBeNull();
    const th = screen.getByRole("columnheader", { name: /^inner/ });
    const text = "Counts of this run's inner runs (sweep trials, fleet pods)";
    expect(th).toHaveAttribute("title", text);
    expect(th).toHaveAccessibleDescription(text);
  });

  it("sums an outer run's inner runs in one line, each state colour-coded and named", async () => {
    serve([outer(2), single(1)]);
    renderBoard();
    await screen.findByText("0.0.2-dev.x");
    const td = innerCell("0.0.2-dev.x");
    const visible = td.querySelector("[aria-hidden]") as HTMLElement;
    expect(visible.textContent).toBe("4 · 2 running · 1 waiting · 1 done");
    expect(td.querySelector(".inner-running")?.textContent).toBe("2 running");
    expect(td.querySelector(".inner-waiting")?.textContent).toBe("1 waiting");
    expect(td.querySelector(".sr-only")?.textContent).toBe("4 inner runs, 2 running, 1 waiting, 1 done");
    expect(innerCell("0.0.1-dev.x").textContent).toBe("");
  });

  it("leaves the inner count out of the experiment cell while it shows, keeping the run's name room", async () => {
    serve([outer(2)]);
    const { unmount } = renderBoard();
    await screen.findByText("0.0.2-dev.x");
    const exp = () => rowOf("0.0.2-dev.x").querySelector('td[data-col-id="experiment"]')!;
    expect(exp().textContent).not.toMatch(/4 inner/);
    unmount();
    renderBoard("/ws/test/app/my-app?hide=c:inner");
    await screen.findByText("0.0.2-dev.x");
    expect(exp().textContent).toMatch(/4 inner/);
  });

  it("is left out when no run on the board is an outer run", async () => {
    serve([single(2), single(1)]);
    renderBoard();
    await screen.findByText("0.0.2-dev.x");
    expect(colIds()).not.toContain("c:inner");
  });

  it("shows once the user turns it on in the column picker, and keeps it in the URL", async () => {
    serve([single(1)]);
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    fireEvent.click(screen.getByRole("button", { name: /columns/i }));
    const box = screen.getByRole("checkbox", { name: "inner" });
    expect(box).not.toBeChecked();
    fireEvent.click(box);
    await waitFor(() => expect(colIds()).toContain("c:inner"));
    expect(urlParams().getAll("show")).toContain("c:inner");
  });

  it("stays hidden once the user turns it off, whatever the rows", async () => {
    serve([outer(1)]);
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    fireEvent.click(screen.getByRole("button", { name: /columns/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: "inner" }));
    await waitFor(() => expect(colIds()).not.toContain("c:inner"));
    expect(urlParams().getAll("hide")).toContain("c:inner");
  });
});
