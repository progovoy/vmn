import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createQueryClient } from "../../queryClient";
import type { RowsFilter } from "../../queries";
import type { GroupBy } from "../../util/groupBy";

const paged = vi.fn();
const firstPage = vi.fn();
const groups = vi.fn();
vi.mock("../../api", () => ({
  api: {
    experimentsPaged: (...a: unknown[]) => paged(...a),
    experiments: (...a: unknown[]) => firstPage(...a),
    experimentGroups: (...a: unknown[]) => groups(...a),
    experimentGroupRows: vi.fn(),
  },
}));

import { useBoardRows } from "../useBoardRows";

const HINT = 'kind = "launch" matches nothing; did you mean tags.kind?';

function mount(filter: RowsFilter, group: GroupBy) {
  const client = createQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useBoardRows("w", "app", filter, {
    group, aggregateInUrl: null, collapsed: new Set(),
  }), { wrapper });
}

describe("useBoardRows hints (plan 31 §4.2)", () => {
  beforeEach(() => { paged.mockReset(); firstPage.mockReset(); groups.mockReset(); });

  it("carries a paged answer's hints", async () => {
    paged.mockResolvedValue({ rows: [], total: 0, next_cursor: null, hints: [HINT] });
    const { result } = mount({ query: 'kind = "launch"', top: true }, "none");
    await waitFor(() => expect(result.current.hints).toEqual([HINT]));
  });

  it("carries the first page's hints", async () => {
    firstPage.mockResolvedValue(Object.assign([], { total: 0, next_cursor: null, hints: [HINT] }));
    const { result } = mount({ query: 'kind = "launch"' }, "none");
    await waitFor(() => expect(result.current.hints).toEqual([HINT]));
  });

  it("carries a grouped answer's hints", async () => {
    groups.mockResolvedValue({
      groups: [], total_groups: 0, total_rows: 0, aggregate: "mean", running: 0,
      metric: null, goal: null, hints: [HINT],
    });
    const { result } = mount({ query: 'kind = "launch"' }, "parent");
    await waitFor(() => expect(result.current.hints).toEqual([HINT]));
  });
});
