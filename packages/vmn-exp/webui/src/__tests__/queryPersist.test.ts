/** Index-backed answers (board first pages, facets, statuses, app lists,
 *  outer-run summaries) persist in localStorage under a size cap, oldest
 *  out first, and are restored into a fresh client; nothing per run, and
 *  storage that does not parse is ignored. */
import { describe, it, expect, beforeEach } from "vitest";
import { createQueryClient } from "../queryClient";
import {
  PERSIST_KEY, clearPersistedQueries, isPersistable, persistQueries, restoreQueries,
} from "../queryPersist";
import { rowsKey, type RowsData } from "../queries";
import { PAGE_SIZE } from "../paging";
import type { ExperimentRow } from "../types";

const row = (i: number) => ({ idx: i, verstr: `0.0.${i}-dev.x`, metrics: {}, params: {} }) as unknown as ExperimentRow;
const page = (n: number, extra: Partial<RowsData> = {}): RowsData =>
  ({ rows: Array.from({ length: n }, (_, i) => row(n - i)), total: n, ...extra });
const stored = () => JSON.parse(localStorage.getItem(PERSIST_KEY) ?? "[]") as { k: unknown[] }[];
const storedKeys = () => stored().map((e) => JSON.stringify(e.k));

beforeEach(() => localStorage.clear());

describe("what is persisted", () => {
  it("index-backed answers only: never a run's detail, its row, the meta or an unknown key", () => {
    expect(isPersistable(rowsKey("ws", "app", { sort: "idx", top: "singles" }))).toBe(true);
    expect(isPersistable(["facets", "ws", "app"])).toBe(true);
    expect(isPersistable(["app-status", "ws", "app"])).toBe(true);
    expect(isPersistable(["apps-status", "ws"])).toBe(true);
    expect(isPersistable(["apps", "ws"])).toBe(true);
    expect(isPersistable(["metrics-schema", "ws", "app"])).toBe(true);
    expect(isPersistable(["job", "ws", "app", "0.0.1", "summary"])).toBe(true);
    expect(isPersistable(["experiment", "ws", "app", "0.0.1"])).toBe(false);
    expect(isPersistable(["run-row", "ws", "app", "0.0.1"])).toBe(false);
    expect(isPersistable(["job", "ws", "app", "0.0.1", "failures", 3])).toBe(false);
    expect(isPersistable(["experiments", "ws", "app", "sweep", "0.0.1"])).toBe(false);
    expect(isPersistable(["meta"])).toBe(false);
    expect(isPersistable(["run-patch", "ws", "app", "0.0.1"])).toBe(false);
  });

  it("writes the persistable answers of the cache, and only them", () => {
    const a = createQueryClient();
    const p = persistQueries(a);
    a.setQueryData(["facets", "ws", "app"], { total: 3 });
    a.setQueryData(["experiment", "ws", "app", "0.0.1"], { verstr: "0.0.1" });
    a.setQueryData(["meta"], { principal: "me" });
    p.flush();
    expect(storedKeys()).toEqual([JSON.stringify(["facets", "ws", "app"])]);
    p.stop();
  });

  it("a board list keeps its first page only, with no cursor or held change", () => {
    const a = createQueryClient();
    const p = persistQueries(a);
    const key = rowsKey("ws", "app", { sort: "idx" });
    a.setQueryData(key, page(PAGE_SIZE + 50, { next_cursor: "c3", held: { added: 2, reordered: false } }));
    p.flush();
    const b = createQueryClient();
    restoreQueries(b);
    const data = b.getQueryData<RowsData>(key)!;
    expect(data.rows).toHaveLength(PAGE_SIZE);
    expect(data.total).toBe(PAGE_SIZE + 50);
    expect(data.next_cursor).toBeUndefined();
    expect(data.held).toBeUndefined();
    p.stop();
  });
});

describe("restoring", () => {
  it("fills a fresh client with the answers and their age, so they revalidate", () => {
    const a = createQueryClient();
    const p = persistQueries(a);
    const key = rowsKey("ws", "app", { sort: "idx", top: "jobs" });
    a.setQueryData(key, page(3), { updatedAt: 1_000 });
    p.flush();
    const b = createQueryClient();
    expect(restoreQueries(b)).toBe(1);
    expect(b.getQueryData<RowsData>(key)!.rows.map((r) => r.idx)).toEqual([3, 2, 1]);
    expect(b.getQueryState(key)!.dataUpdatedAt).toBe(1_000);
    p.stop();
  });

  it("ignores storage that does not parse, or entries of the wrong shape", () => {
    localStorage.setItem(PERSIST_KEY, "{not json");
    const b = createQueryClient();
    expect(restoreQueries(b)).toBe(0);
    localStorage.setItem(PERSIST_KEY, JSON.stringify([{ k: "nope" }, null, { k: ["facets", "w", "a"], d: { total: 1 }, t: 5 }]));
    expect(restoreQueries(b)).toBe(1);
    expect(b.getQueryData(["facets", "w", "a"])).toEqual({ total: 1 });
  });

  it("clearing (sign-out) drops every persisted answer", () => {
    const a = createQueryClient();
    const p = persistQueries(a);
    a.setQueryData(["facets", "ws", "app"], { total: 3 });
    p.flush();
    clearPersistedQueries();
    expect(localStorage.getItem(PERSIST_KEY)).toBeNull();
    p.stop();
  });
});

describe("the size cap", () => {
  it("drops the least recently updated answers first", () => {
    const a = createQueryClient();
    const one = JSON.stringify({ k: ["facets", "ws", "a1"], d: { blob: "x".repeat(1_000) }, t: 1 }).length;
    const p = persistQueries(a, { maxChars: one * 2 + 10 });
    for (const [i, t] of [[1, 100], [2, 300], [3, 200]]) {
      a.setQueryData(["facets", "ws", `a${i}`], { blob: "x".repeat(1_000) }, { updatedAt: t });
    }
    p.flush();
    expect(storedKeys().sort()).toEqual([
      JSON.stringify(["facets", "ws", "a2"]), JSON.stringify(["facets", "ws", "a3"]),
    ]);
    p.stop();
  });

  it("keeps what another tab or session stored, under the same cap", () => {
    const a = createQueryClient();
    let p = persistQueries(a);
    a.setQueryData(["facets", "ws", "old"], { total: 1 }, { updatedAt: 10 });
    p.flush();
    p.stop();
    const b = createQueryClient();
    p = persistQueries(b);
    b.setQueryData(["facets", "ws", "new"], { total: 2 }, { updatedAt: 20 });
    p.flush();
    expect(storedKeys().sort()).toEqual([
      JSON.stringify(["facets", "ws", "new"]), JSON.stringify(["facets", "ws", "old"]),
    ]);
    p.stop();
  });
});
