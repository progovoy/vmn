/** Labels for the selection chips (`@N name`, verstr in the title) without
 *  loading each run: a run detail another tab already fetched, a cached
 *  leaderboard row, else one bounded lookup of the whole selection. */
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { findCachedRow, runQuery } from "../../queries";
import { runText } from "../../shell/crumbs";
import { verstrInQuery } from "../../util/searchQuery";

export interface RunChipLabel {
  ref: string;
  text: string;
  /** Loading the run (on the table tab) failed: an unknown ref. */
  missing: boolean;
}

export function useRunLabels(ws: string, app: string, refs: string[]): RunChipLabel[] {
  const client = useQueryClient();
  // enabled: false only watches the cache, so the curves tab loads no detail.
  const details = useQueries({
    queries: refs.map((v) => ({ ...runQuery(ws, app, v), enabled: false })),
  }, client);
  const lookup = useQuery({
    queryKey: ["compare-labels", ws, app, refs],
    queryFn: () => api.experimentsPaged(ws, app, {
      query: verstrInQuery(refs), limit: refs.length, archived: true,
    }).then((page) => page.rows),
    enabled: refs.length > 0,
    staleTime: 60_000,
    retry: false,
  }, client);

  return refs.map((ref, i) => {
    const d = details[i]?.data;
    const row = findCachedRow(client, ws, app, ref) ?? lookup.data?.find((r) => r.verstr === ref);
    const idx = d?.idx ?? row?.idx ?? null;
    const name = (d?.name ?? row?.name ?? null) || null;
    return {
      ref,
      text: idx == null ? ref : runText({ verstr: ref, idx, name }),
      missing: !!details[i]?.error,
    };
  });
}
