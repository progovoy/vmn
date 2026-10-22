/** The request cache kept across reloads: index-backed answers (each top
 *  view's board first page, facets, app and workspace statuses, app lists,
 *  metric schemas, outer-run summaries) are written to localStorage under a
 *  size cap, the least recently updated dropped first, and restored into the
 *  client at startup with their age, so a reload paints at once and every
 *  restored answer revalidates on its first use. Never a run's own (store
 *  backed) reads, nor `/meta` (the principal); tokens live in sessionStorage. */
import type { Query, QueryClient, QueryKey } from "@tanstack/react-query";
import { PAGE_SIZE } from "./paging";
import type { RowsData } from "./queries";

export const PERSIST_KEY = "vmn-exp:query-cache:v1";
/** About 3 MB of the origin's ~5 MB of localStorage (UTF-16 code units). */
export const PERSIST_MAX_CHARS = 3_000_000;
/** Writes wait this long, so a burst of answers is one write. */
const WRITE_DELAY_MS = 2_000;

type Entry = { k: unknown[]; d: unknown; t: number };

const APP_LEVEL = new Set(["facets", "app-status", "metrics-schema"]);
const WORKSPACE_LEVEL = new Set(["apps", "apps-status"]);

/** Whether answers of *key* are index reads worth keeping across reloads. */
export function isPersistable(key: QueryKey): boolean {
  const [kind] = key;
  if (typeof kind !== "string") return false;
  if (kind === "workspaces") return key.length === 1;
  if (WORKSPACE_LEVEL.has(kind)) return key.length === 2;
  if (APP_LEVEL.has(kind)) return key.length === 3 || (kind === "facets" && key.length === 4 && isObject(key[3]));
  if (kind === "experiments") return key.length === 4 && isObject(key[3]);
  if (kind === "job") return key.length === 5 && key[4] === "summary";
  return false;
}

const isObject = (v: unknown) => typeof v === "object" && v !== null && !Array.isArray(v);

/** A board list as its first page: later pages are paged again on demand. */
function trimmed(key: QueryKey, data: unknown): unknown {
  if (key[0] !== "experiments") return data;
  const { held: _held, ...page } = data as RowsData;
  if (page.rows.length <= PAGE_SIZE) return page;
  const { next_cursor: _cursor, ...rest } = page;
  return { ...rest, rows: page.rows.slice(0, PAGE_SIZE) };
}

function readEntries(storage: Storage): Entry[] {
  try {
    const parsed: unknown = JSON.parse(storage.getItem(PERSIST_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((e): e is Entry =>
      isObject(e) && Array.isArray(e.k) && isPersistable(e.k) && e.d !== undefined && typeof e.t === "number");
  } catch {
    return [];
  }
}

/** Fill *client* with the stored answers; the number restored. */
export function restoreQueries(client: QueryClient, storage: Storage = localStorage): number {
  const entries = readEntries(storage);
  for (const e of entries) client.setQueryData(e.k, e.d, { updatedAt: e.t });
  return entries.length;
}

export function clearPersistedQueries(storage: Storage = localStorage) {
  try { storage.removeItem(PERSIST_KEY); } catch { /* nothing stored */ }
}

const persisted = (q: Query) => q.state.status === "success" && q.state.data !== undefined && isPersistable(q.queryKey);

/** The newest entries that fit in *maxChars*, newest first. */
function capped(entries: Entry[], maxChars: number): string {
  const out: string[] = [];
  let size = 2;
  for (const e of [...entries].sort((a, b) => b.t - a.t)) {
    const json = JSON.stringify(e);
    if (size + json.length + 1 > maxChars) continue;
    out.push(json);
    size += json.length + 1;
  }
  return `[${out.join(",")}]`;
}

/** Keep *client*'s persistable answers in storage from now on: written a
 *  moment after they arrive and when the page is hidden. */
export function persistQueries(client: QueryClient, opts: { storage?: Storage; maxChars?: number } = {}) {
  const storage = opts.storage ?? localStorage;
  const maxChars = opts.maxChars ?? PERSIST_MAX_CHARS;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const flush = () => {
    clearTimeout(timer);
    timer = undefined;
    const byKey = new Map<string, Entry>();
    for (const e of readEntries(storage)) byKey.set(JSON.stringify(e.k), e);
    for (const q of client.getQueryCache().getAll()) {
      if (!persisted(q)) continue;
      const e = { k: q.queryKey as unknown[], d: trimmed(q.queryKey, q.state.data), t: q.state.dataUpdatedAt };
      const id = JSON.stringify(e.k);
      if ((byKey.get(id)?.t ?? -1) <= e.t) byKey.set(id, e);
    }
    try {
      storage.setItem(PERSIST_KEY, capped([...byKey.values()], maxChars));
    } catch { /* full or unavailable: the cache stays in memory only */ }
  };

  const unsubscribe = client.getQueryCache().subscribe((event) => {
    if (event.type !== "updated" || event.action.type !== "success" || !isPersistable(event.query.queryKey)) return;
    if (timer === undefined) timer = setTimeout(flush, WRITE_DELAY_MS);
  });
  const onHide = () => { if (timer !== undefined) flush(); };
  window.addEventListener("pagehide", onHide);

  return {
    flush,
    stop: () => {
      clearTimeout(timer);
      unsubscribe();
      window.removeEventListener("pagehide", onHide);
    },
  };
}
