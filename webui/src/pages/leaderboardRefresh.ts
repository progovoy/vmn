import { MAX_PAGE, PAGE_SIZE } from "../paging";

type Page<R> = { rows: R[]; total: number };
type PageFetch<O, R> = (opts: O & { offset: number; limit: number }) => Promise<Page<R>>;

/** Re-fetch the first *loaded* rows (at least one page) with the same filters,
 *  in requests of at most MAX_PAGE rows — the server caps `limit`, so a single
 *  large request would silently drop everything past the cap. */
export async function refreshLoaded<O extends object, R>(
  fetchPage: PageFetch<O, R>,
  opts: O,
  loaded: number,
  pageSize = PAGE_SIZE,
): Promise<Page<R>> {
  const want = Math.max(loaded, pageSize);
  const rows: R[] = [];
  let total = 0;
  for (let offset = 0; offset < want; offset += MAX_PAGE) {
    const limit = Math.min(MAX_PAGE, want - offset);
    const page = await fetchPage({ ...opts, offset, limit });
    rows.push(...page.rows);
    total = page.total;
    if (page.rows.length < limit) break;
  }
  return { rows, total };
}
