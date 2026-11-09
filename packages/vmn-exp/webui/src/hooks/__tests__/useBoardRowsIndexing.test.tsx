/** A board answer over an index still loading carries `indexing` (plan 33
 *  §2.2): the board reads it from the answer, flat, first page or grouped. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createQueryClient } from "../../queryClient";
import type { RowsFilter } from "../../queries";
import type { GroupBy } from "../../util/groupBy";

const paged = vi.fn();
const firstPage = vi.fn();
const groups = vi.fn();
vi.mock("../../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api")>();
  return {
    api: {
      experimentsPaged: (...a: unknown[]) => paged(...a),
      experiments: (...a: unknown[]) => firstPage(...a),
      experimentGroups: (...a: unknown[]) => groups(...a),
      experimentGroupRows: vi.fn(),
    },
    realApi: real.api,
  };
});

import * as apiModule from "../../api";
import { useBoardRows } from "../useBoardRows";

const INDEXING = { loaded: 120_000, total: 734_000 };

function mount(filter: RowsFilter, group: GroupBy) {
  const client = createQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useBoardRows("w", "app", filter, {
    group, aggregateInUrl: null, collapsed: new Set(),
  }), { wrapper });
}

describe("useBoardRows indexing (plan 33 §2.2)", () => {
  beforeEach(() => { paged.mockReset(); firstPage.mockReset(); groups.mockReset(); });

  it("carries a paged answer's indexing", async () => {
    paged.mockResolvedValue({ rows: [], total: 0, next_cursor: null, indexing: INDEXING });
    const { result } = mount({ top: true }, "none");
    await waitFor(() => expect(result.current.indexing).toEqual(INDEXING));
  });

  it("carries the first page's indexing", async () => {
    firstPage.mockResolvedValue(Object.assign([], { total: 0, next_cursor: null, indexing: INDEXING }));
    const { result } = mount({}, "none");
    await waitFor(() => expect(result.current.indexing).toEqual(INDEXING));
  });

  it("carries a grouped answer's indexing", async () => {
    groups.mockResolvedValue({
      groups: [], total_groups: 0, total_rows: 0, aggregate: "mean", running: 0,
      metric: null, goal: null, indexing: INDEXING,
    });
    const { result } = mount({}, "parent");
    await waitFor(() => expect(result.current.indexing).toEqual(INDEXING));
  });

  it("says nothing of an answer over a loaded index", async () => {
    firstPage.mockResolvedValue(Object.assign([], { total: 0, next_cursor: null }));
    const { result } = mount({}, "none");
    await waitFor(() => expect(result.current.rows).toEqual([]));
    expect(result.current.indexing).toBeUndefined();
  });
});

describe("api.experiments (plan 33 §2.2)", () => {
  const realApi = (apiModule as unknown as { realApi: typeof apiModule.api }).realApi;
  afterEach(() => { vi.unstubAllGlobals(); });

  it("keeps the answer's indexing on the first page", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(
      JSON.stringify({ rows: [], total: 0, indexing: INDEXING }), { status: 200 }))));
    const page = await realApi.experiments("w", "app");
    expect(page.indexing).toEqual(INDEXING);
  });
});
