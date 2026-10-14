import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createQueryClient } from "../../queryClient";
import type { ExperimentRow } from "../../types";

const paged = vi.fn();
vi.mock("../../api", () => ({
  api: { experimentsPaged: (...a: unknown[]) => paged(...a), experiments: vi.fn() },
}));

import { useLeaderboardRows } from "../useLeaderboardRows";

const row = (verstr: string, extra: Partial<ExperimentRow> = {}) =>
  ({ verstr, status: "succeeded", metrics: {}, params: {}, ...extra }) as unknown as ExperimentRow;
const verstrs = (rows?: ExperimentRow[]) => rows?.map((r) => r.verstr);
const FILTER = { order: "desc" as const, sort: "loss" };

function mount() {
  const client = createQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useLeaderboardRows("w", "app", FILTER), { wrapper });
}

describe("useLeaderboardRows paging (plan 23 W6)", () => {
  beforeEach(() => paged.mockReset());

  it("loads more after the server's next_cursor, and stops at a null one", async () => {
    paged.mockResolvedValueOnce({ rows: [row("a"), row("b")], total: 4, next_cursor: "c1" });
    const { result } = mount();
    await waitFor(() => expect(verstrs(result.current.rows)).toEqual(["a", "b"]));
    expect(result.current.hasMore).toBe(true);
    paged.mockResolvedValueOnce({ rows: [row("c"), row("d")], total: 4, next_cursor: null });
    await act(() => result.current.loadMore());
    expect(paged.mock.calls[1][2]).toMatchObject({ cursor: "c1" });
    expect(paged.mock.calls[1][2].offset).toBeUndefined();
    expect(verstrs(result.current.rows)).toEqual(["a", "b", "c", "d"]);
    expect(result.current.hasMore).toBe(false);
  });

  it("falls back to the offset when the server sends no cursor", async () => {
    paged.mockResolvedValueOnce({ rows: [row("a"), row("b")], total: 3 });
    const { result } = mount();
    await waitFor(() => expect(result.current.rows).toBeDefined());
    paged.mockResolvedValueOnce({ rows: [row("c")], total: 3 });
    await act(() => result.current.loadMore());
    expect(paged.mock.calls[1][2]).toMatchObject({ offset: 2 });
    expect(paged.mock.calls[1][2].cursor).toBeUndefined();
    expect(result.current.hasMore).toBe(false);
  });

  it("keeps the rows in place while held, counting the new ones, until shown", async () => {
    paged.mockResolvedValueOnce({ rows: [row("a"), row("b")], total: 2, next_cursor: null });
    const { result } = mount();
    await waitFor(() => expect(result.current.rows).toBeDefined());
    const toTop = vi.fn();
    result.current.viewportRef.current = { held: () => true, toTop };
    const fresh = { rows: [row("n1"), row("n2"), row("b", { status: "failed" }), row("a")], total: 4, next_cursor: "c2" };
    paged.mockResolvedValueOnce(fresh);
    await act(async () => { await result.current.refresh(); });
    expect(verstrs(result.current.rows)).toEqual(["a", "b"]);
    expect(result.current.rows?.[1].status).toBe("failed");
    expect(result.current.total).toBe(4);
    expect(result.current.pending).toEqual({ added: 2, reordered: true });

    paged.mockResolvedValueOnce(fresh);
    await act(() => result.current.showNew());
    expect(verstrs(result.current.rows)).toEqual(["n1", "n2", "b", "a"]);
    expect(result.current.pending).toBeNull();
    expect(result.current.hasMore).toBe(true);
    expect(toTop).toHaveBeenCalled();
  });

  it("applies a change directly at the top of the list with nothing selected", async () => {
    paged.mockResolvedValueOnce({ rows: [row("a")], total: 1, next_cursor: null });
    const { result } = mount();
    await waitFor(() => expect(result.current.rows).toBeDefined());
    paged.mockResolvedValueOnce({ rows: [row("n"), row("a")], total: 2, next_cursor: null });
    await act(async () => { await result.current.refresh(); });
    expect(verstrs(result.current.rows)).toEqual(["n", "a"]);
    expect(result.current.pending).toBeNull();
  });
});
