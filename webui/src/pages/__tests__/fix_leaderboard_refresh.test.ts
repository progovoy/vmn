import { describe, it, expect, vi } from "vitest";
import { refreshLoaded } from "../leaderboardRefresh";
import { MAX_PAGE } from "../../paging";

type Row = { verstr: string };

function fakeServer(total: number) {
  // Mirrors the server: never more than MAX_PAGE rows per response.
  return vi.fn(async (opts: { offset?: number; limit?: number; sort?: string }) => {
    const offset = opts.offset ?? 0;
    const limit = Math.min(opts.limit ?? 200, MAX_PAGE);
    const rows: Row[] = [];
    for (let i = offset; i < Math.min(offset + limit, total); i++) rows.push({ verstr: `r${i}` });
    return { rows, total };
  });
}

describe("refreshLoaded", () => {
  it("re-fetches every loaded row even past the server's per-request cap", async () => {
    const fetchPage = fakeServer(5000);
    const out = await refreshLoaded(fetchPage, { sort: "loss" }, 2500);

    expect(out.rows).toHaveLength(2500);
    expect(out.rows[2499].verstr).toBe("r2499");
    expect(out.total).toBe(5000);
    for (const [opts] of fetchPage.mock.calls) {
      expect(opts.limit).toBeLessThanOrEqual(MAX_PAGE);
      expect(opts.sort).toBe("loss");
    }
  });

  it("asks for at least one page when nothing was loaded yet", async () => {
    const fetchPage = fakeServer(50);
    const out = await refreshLoaded(fetchPage, {}, 0, 200);
    expect(fetchPage).toHaveBeenCalledTimes(1);
    expect(fetchPage.mock.calls[0][0]).toMatchObject({ offset: 0, limit: 200 });
    expect(out.rows).toHaveLength(50);
  });

  it("stops early when the server runs out of rows", async () => {
    const fetchPage = fakeServer(1200);
    const out = await refreshLoaded(fetchPage, {}, 3000);
    expect(out.rows).toHaveLength(1200);
    expect(fetchPage).toHaveBeenCalledTimes(2);
  });
});
