import { describe, it, expect, vi } from "vitest";
import { chunk, refreshRows } from "../leaderboardRefresh";

type Row = { verstr: string; status?: string; v?: number };
const r = (verstr: string, extra: Partial<Row> = {}): Row => ({ verstr, ...extra });

describe("chunk", () => {
  it("splits into pieces of at most n", () => {
    expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]]);
  });
});

describe("refreshRows", () => {
  it("fetches only the first page when nothing past it is loaded", async () => {
    const fetchFirst = vi.fn(async () => ({ rows: [r("a"), r("b")], total: 2 }));
    const fetchWhere = vi.fn();
    const out = await refreshRows({
      getRows: () => [r("a"), r("b")], fetchFirst, fetchWhere,
    });
    expect(fetchWhere).not.toHaveBeenCalled();
    expect(out.rows.map((x) => x.verstr)).toEqual(["a", "b"]);
    expect(out.total).toBe(2);
  });

  it("re-asks for running rows past the first page by verstr and patches them in place", async () => {
    const tailIdle = r("c", { status: "succeeded" });
    const prev = [r("a"), r("b"), tailIdle, r("d", { status: "running", v: 1 })];
    const fetchFirst = vi.fn(async () => ({ rows: [r("a"), r("b")], total: 9 }));
    const fetchWhere = vi.fn(async (_q: string, _l: number) => ({ rows: [r("d", { status: "succeeded", v: 2 })] }));
    const out = await refreshRows({ getRows: () => prev, fetchFirst, fetchWhere });

    expect(fetchWhere).toHaveBeenCalledTimes(1);
    expect(fetchWhere.mock.calls[0][0]).toBe('verstr in ("d")');
    expect(out.rows.map((x) => x.verstr)).toEqual(["a", "b", "c", "d"]);
    expect(out.rows[2]).toBe(tailIdle);
    expect(out.rows[3]).toMatchObject({ status: "succeeded", v: 2 });
    expect(out.total).toBe(9);
  });

  it("also refreshes the extra (visible) rows it is given", async () => {
    const prev = [r("a"), r("x"), r("y")];
    const fetchFirst = vi.fn(async () => ({ rows: [r("a")], total: 3 }));
    const fetchWhere = vi.fn(async (_q: string, _l: number) => ({ rows: [r("y", { v: 5 })] }));
    const out = await refreshRows({
      getRows: () => prev, fetchFirst, fetchWhere, extraVerstrs: ["y", "a"],
    });
    expect(fetchWhere.mock.calls[0][0]).toBe('verstr in ("y")');
    expect(out.rows[2]).toMatchObject({ v: 5 });
  });

  it("drops a re-asked row the filters no longer match", async () => {
    const prev = [r("a"), r("gone", { status: "running" })];
    const out = await refreshRows({
      getRows: () => prev,
      fetchFirst: async () => ({ rows: [r("a")], total: 1 }),
      fetchWhere: async () => ({ rows: [] }),
    });
    expect(out.rows.map((x) => x.verstr)).toEqual(["a"]);
  });

  it("asks in chunks of at most 200 verstrs", async () => {
    const tail = Array.from({ length: 450 }, (_, i) => r(`t${i}`, { status: "running" }));
    const fetchWhere = vi.fn(async (_q: string, _limit: number) => ({ rows: [] as Row[] }));
    await refreshRows({
      getRows: () => [r("a"), ...tail],
      fetchFirst: async () => ({ rows: [r("a")], total: 451 }),
      fetchWhere,
    });
    expect(fetchWhere).toHaveBeenCalledTimes(3);
    for (const [, limit] of fetchWhere.mock.calls) expect(limit).toBeLessThanOrEqual(200);
  });

  it("keeps rows a new first page pushed down, and never duplicates", async () => {
    const prev = [r("a"), r("b"), r("c")];
    const out = await refreshRows({
      getRows: () => prev,
      fetchFirst: async () => ({ rows: [r("new"), r("a")], total: 4 }),
      fetchWhere: async () => ({ rows: [] }),
    });
    expect(out.rows.map((x) => x.verstr)).toEqual(["new", "a", "b", "c"]);
  });

  it("holds the rows in place, drops a re-asked one that no longer matches, keeps the held cursor", async () => {
    const prev = [r("a"), r("b"), r("c", { status: "running" }), r("gone", { status: "running" })];
    const out = await refreshRows({
      getRows: () => prev,
      fetchFirst: async () => ({ rows: [r("new"), r("b", { v: 2 })], total: 5, next_cursor: "first" }),
      fetchWhere: async () => ({ rows: [r("c", { status: "succeeded" })] }),
      hold: true,
      getCursor: () => "held",
    });
    expect(out.rows.map((x) => x.verstr)).toEqual(["a", "b", "c"]);
    expect(out.rows[0]).toBe(prev[0]);
    expect(out.rows[1]).toMatchObject({ v: 2 });
    expect(out.rows[2]).toMatchObject({ status: "succeeded" });
    expect(out.held).toEqual({ added: 1, reordered: false });
    expect(out.next_cursor).toBe("held");
  });

  it("keeps the held cursor while rows past the first page are kept, else the first page's", async () => {
    const page = { rows: [r("a")], total: 3, next_cursor: "first" };
    const opts = { fetchFirst: async () => page, fetchWhere: async () => ({ rows: [] }), getCursor: () => "held" };
    expect((await refreshRows({ ...opts, getRows: () => [r("a"), r("b")] })).next_cursor).toBe("held");
    expect((await refreshRows({ ...opts, getRows: () => [r("a")] })).next_cursor).toBe("first");
  });
});
