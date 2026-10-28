/** Plan 28 N6: an outer run's tree (`experiments?children_of=`): its children
 *  as a tree grid, each node with its run bar, worst attention, best value and
 *  duration against its siblings; children load when a node opens, the
 *  server's `open` nodes start open, and the arrows and Enter fold them. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../../../apiTree", async (orig) => ({
  ...(await orig<typeof import("../../../apiTree")>()),
  fetchChildren: vi.fn(),
}));
vi.mock("../../../api", () => ({ api: { metricsSchema: vi.fn() } }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count, estimateSize }: { count: number; estimateSize: (i: number) => number }) => ({
    getTotalSize: () => count * 40,
    scrollToIndex: () => {},
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 40, size: estimateSize(index), end: (index + 1) * 40,
      })),
  }),
}));

import { api } from "../../../api";
import { fetchChildren, type TreePage, type TreeRow } from "../../../apiTree";
import type { AttentionEntry } from "../../../shell/contracts";
import { job } from "../../../util/__tests__/jobFixture";
import JobTree from "../JobTree";

const LAUNCH = "1.0.0-dev.launch";
const fetched = fetchChildren as unknown as ReturnType<typeof vi.fn>;
const ATTENTION: AttentionEntry[] = [{ key: "unstable", label: "unstable", level: "error", count: 1, q: "q" }];

const row = (name: string, extra: Partial<TreeRow> = {}): TreeRow => ({
  idx: 1, verstr: `1.0.0-dev.${name}`, name, code_verstr: "1.0.0", timestamp: null, note: null,
  branch: null, base_version: null, metrics: {}, status: "succeeded", tree_status: "succeeded",
  job: null, open: false, ...extra,
} as TreeRow);
const node = (name: string, extra: Partial<TreeRow> = {}) =>
  row(name, { job: job({ metric: "loss", best: 0.182 }), children: ["x"], kind: "outer", ...extra });

const CHILDREN: Record<string, TreeRow[]> = {
  [LAUNCH]: [
    node("d1"),
    node("d2", { open: true, tags: { kind: "date" }, metrics: { loss: 0.5 },
                 job: job({ metric: "loss", best: 0.25, attention: { unstable: 1 } }) }),
    row("solo", { duration_sec: 600, duration_ratio: 3.1 }),
  ],
  "1.0.0-dev.d1": [row("t3")],
  "1.0.0-dev.d2": [row("t1", { attention: { unstable: 1 } }), row("t2")],
};

const page = (rows: TreeRow[], total = rows.length): TreePage =>
  ({ rows, total, next_cursor: null, tree_columns: { date: ["m:loss", "t:kind"] } });

function renderTree() {
  return renderWithClient(
    <MemoryRouter>
      <JobTree ws="test" app="my-app" verstr={LAUNCH} attention={ATTENTION} />
    </MemoryRouter>,
  );
}

const treeRow = (name: string) => screen.getByRole("link", { name }).closest("tr")!;
const parents = () => fetched.mock.calls.map((c) => c[2]);

beforeEach(() => {
  vi.clearAllMocks();
  (api.metricsSchema as ReturnType<typeof vi.fn>).mockResolvedValue({ loss: { goal: "min" } });
  fetched.mockImplementation(async (_ws: string, _app: string, parent: string) => page(CHILDREN[parent] ?? []));
});

describe("an outer run's tree", () => {
  it("lists its children as the tree's first level", async () => {
    renderTree();
    const grid = await screen.findByRole("treegrid", { name: /runs of/ });
    await within(grid).findByRole("link", { name: "d1" });
    for (const name of ["d1", "d2", "solo"]) expect(treeRow(name)).toHaveAttribute("aria-level", "1");
    expect(treeRow("d1")).toHaveAttribute("aria-expanded", "false");
    expect(treeRow("solo")).not.toHaveAttribute("aria-expanded");
  });

  it("opens the nodes the server marks open and folds the rest", async () => {
    renderTree();
    expect(await screen.findByRole("link", { name: "t1" })).toBeInTheDocument();
    expect(treeRow("d2")).toHaveAttribute("aria-expanded", "true");
    expect(treeRow("t1")).toHaveAttribute("aria-level", "2");
    expect(parents()).not.toContain("1.0.0-dev.d1");
  });

  it("loads a folded node's children when it opens, and folds them again", async () => {
    renderTree();
    fireEvent.click(await screen.findByRole("button", { name: "expand d1" }));
    expect(await screen.findByRole("link", { name: "t3" })).toBeInTheDocument();
    expect(parents()).toContain("1.0.0-dev.d1");
    fireEvent.click(screen.getByRole("button", { name: "collapse d1" }));
    await waitFor(() => expect(screen.queryByRole("link", { name: "t3" })).toBeNull());
  });

  it("folds and unfolds with the arrows and Enter", async () => {
    renderTree();
    await screen.findByRole("link", { name: "t1" });
    const d1 = treeRow("d1");
    d1.focus();
    fireEvent.keyDown(d1, { key: "ArrowRight" });
    await waitFor(() => expect(treeRow("d1")).toHaveAttribute("aria-expanded", "true"));
    fireEvent.keyDown(treeRow("d1"), { key: "ArrowLeft" });
    await waitFor(() => expect(treeRow("d1")).toHaveAttribute("aria-expanded", "false"));
    fireEvent.keyDown(treeRow("d1"), { key: "ArrowDown" });
    await waitFor(() => expect(treeRow("d2")).toHaveFocus());
    fireEvent.keyDown(treeRow("d2"), { key: "Enter" });
    await waitFor(() => expect(screen.queryByRole("link", { name: "t1" })).toBeNull());
  });

  it("shows each node's worst attention, best value and duration against its siblings", async () => {
    renderTree();
    await screen.findByRole("link", { name: "t1" });
    expect(within(treeRow("d2")).getByText("1 unstable")).toBeInTheDocument();
    expect(within(treeRow("t1")).getByText("1 unstable")).toBeInTheDocument();
    expect(within(treeRow("d2")).getByText("0.25")).toBeInTheDocument();
    expect(within(treeRow("solo")).getByText("3.1× siblings")).toBeInTheDocument();
  });

  it("shows the columns the app's settings name for a node's kind", async () => {
    renderTree();
    await screen.findByRole("link", { name: "t1" });
    const fields = treeRow("d2").querySelector('[data-col-id="fields"]')!;
    expect(fields.textContent).toContain("loss");
    expect(fields.textContent).toContain("0.5");
    expect(fields.textContent).toContain("date");
    expect(treeRow("d1").querySelector('[data-col-id="fields"]')!.textContent).toBe("");
  });

  it("loads more of a node's children on its `+N more` row", async () => {
    fetched.mockImplementation(async (_ws: string, _app: string, parent: string, opts: { offset?: number }) =>
      parent === LAUNCH && !opts?.offset ? page([row("a"), row("b")], 3)
        : parent === LAUNCH ? page([row("c")], 3) : page([]));
    renderTree();
    fireEvent.click(await screen.findByRole("button", { name: "+1 more" }));
    expect(await screen.findByRole("link", { name: "c" })).toBeInTheDocument();
    expect(fetched.mock.calls.some((c) => c[2] === LAUNCH && c[3]?.offset === 2)).toBe(true);
  });
});
