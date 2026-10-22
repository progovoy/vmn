/** The latest answer the request cache holds for another filter of a
 *  board list's *view*: what a board remounted on a filter never answered
 *  (Back) paints while it loads. */
import type { QueryClient, QueryKey } from "@tanstack/react-query";

/** Among keys like *key* (same prefix and length, any last element, the
 *  filter) whose filter *sameView* accepts. */
export function newestOfView<T>(
  client: QueryClient, key: QueryKey, sameView: (filter: unknown) => boolean,
): T | undefined {
  let best: { at: number; data: T } | undefined;
  for (const q of client.getQueryCache().findAll({ queryKey: key.slice(0, -1) })) {
    const { data, dataUpdatedAt: at } = q.state;
    const k = q.queryKey;
    if (data === undefined || k.length !== key.length || !sameView(k[k.length - 1])) continue;
    if (!best || at > best.at) best = { at, data: data as T };
  }
  return best?.data;
}
