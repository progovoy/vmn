/** Plan 34 §3: in an outer run's tree, a lost run reads `stuck · lost`. */
import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../../../apiTree", async (orig) => ({
  ...(await orig<typeof import("../../../apiTree")>()),
  fetchChildren: vi.fn(),
}));
vi.mock("../../../api", () => ({ api: { metricsSchema: vi.fn().mockResolvedValue({}) } }));
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

import { fetchChildren, type TreeRow } from "../../../apiTree";
import JobTree from "../JobTree";

const row = (name: string, extra: Partial<TreeRow> = {}): TreeRow => ({
  idx: 1, verstr: `1.0.0-dev.${name}`, name, code_verstr: "1.0.0", timestamp: null, note: null,
  branch: null, base_version: null, metrics: {}, status: "succeeded", tree_status: "succeeded",
  job: null, open: false, ...extra,
} as TreeRow);

describe("a lost run in the tree", () => {
  it("reads stuck · lost", async () => {
    (fetchChildren as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      rows: [row("ok"), row("gone", { status: "stuck", tree_status: null, settled: "lost" } as Partial<TreeRow>)],
      total: 2, next_cursor: null, tree_columns: {},
    });
    renderWithClient(<MemoryRouter><JobTree ws="test" app="my-app" verstr="1.0.0-dev.launch" /></MemoryRouter>);
    const gone = (await screen.findByRole("link", { name: "gone" })).closest("tr")!;
    expect(gone.querySelector(".status-pill")!.textContent).toContain("stuck · lost");
  });
});
